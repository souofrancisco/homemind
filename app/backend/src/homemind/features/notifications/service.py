"""Orquestração das notificações (síncrona): criar, responder, ler, listar e expirar.

Os serviços são SÍNCRONOS e DEVOLVEM os eventos a emitir (`Outcome.events`): quem os chama
(o barramento, com outbox na mesma transação) é que os publica. As regras de resposta e de
estado são do contrato (`contracts/notification.py`); aqui compõe-se, deduplica-se, persiste-se com
compare-and-set e decide-se a visibilidade.
"""

from dataclasses import dataclass
from datetime import datetime, tzinfo
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.common import Provenance, ValueKind, replace
from homemind.contracts.household import MembershipRole
from homemind.contracts.notification import (
    AlreadyRespondedError,
    ConfirmationRequest,
    Notification,
    NotificationKind,
    NotificationPreferences,
    NotificationScope,
    NotificationStatus,
    NotificationView,
)
from homemind.features.notifications.compose import (
    compose_budget_alert,
    compose_confirmation,
    event_id_for,
)
from homemind.features.notifications.ports import Clock, ResidentDirectory
from homemind.features.notifications.preferences import Delivery, delivery_for
from homemind.features.notifications.repository import NotificationRepository

_OPEN = frozenset({NotificationStatus.unread, NotificationStatus.read})
_DEFAULT_TZ = "Europe/Lisbon"


# Allow-list de tipos que o senhorio pode ver (privacidade: os restantes derivam de presença,
# consumo ou hábitos dos inquilinos, P-18). Um tipo novo fica escondido ao senhorio até ser
# acrescentado aqui de propósito.
_SENHORIO_PODE_VER = frozenset({NotificationKind.info})


@dataclass(frozen=True)
class Outcome:
    """Resultado de uma operação: a notificação (se houver) e os eventos a emitir."""

    notification: Notification | None
    events: tuple[de.DomainEvent, ...] = ()


class NotificationNotFoundError(LookupError):
    """Não existe ou não é visível para o residente (nunca revela qual dos dois)."""

    code = "notification_not_found"


class NotificationService:
    def __init__(
        self,
        repo: NotificationRepository,
        directory: ResidentDirectory,
        clock: Clock,
        tz: tzinfo | None = None,
    ) -> None:
        self._repo = repo
        self._directory = directory
        self._clock = clock
        self._tz = tz if tz is not None else ZoneInfo(_DEFAULT_TZ)

    # --- criação ---------------------------------------------------------------------------

    def on_confirmation_needed(
        self,
        req: ConfirmationRequest,
        *,
        source_event_id: UUID,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`billing.confirmation_needed` -> notificação da casa para os inquilinos elegíveis."""
        now = self._clock()
        if req.expires_at <= now:
            return Outcome(None)  # pedido já caducado: não vale a pena perguntar
        responders = [
            r
            for r in req.eligible_resident_ids
            if self._directory.role_in(household_id, r, now) == MembershipRole.tenant
        ]
        if not responders:
            return Outcome(None)
        n = compose_confirmation(
            req,
            household_id=household_id,
            responder_ids=responders,
            origin=provenance.origin,
            correlation_id=correlation_id,
            source_event_id=source_event_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=True)

    def on_budget_threshold(
        self,
        *,
        source_event_id: UUID,
        household_id: UUID,
        resident_id: UUID,
        budget_id: UUID,
        pct: int,
        spent_cents: int,
        limit_cents: int | None,
        forecast_cents: int | None,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`alerts.threshold_crossed` -> aviso pessoal ao dono do orçamento.

        Sem deduplicação por `(kind, ref, destinatário)`: o mesmo orçamento cruza 50/80/100 %
        e cada limiar tem de ser avisado; a idempotência vem do id derivado do evento.
        """
        now = self._clock()
        if self._directory.role_in(household_id, resident_id, now) is None:
            return Outcome(None)
        n = compose_budget_alert(
            household_id=household_id,
            resident_id=resident_id,
            budget_id=budget_id,
            pct=pct,
            spent_cents=spent_cents,
            limit_cents=limit_cents,
            forecast_cents=forecast_cents,
            origin=provenance.origin,
            correlation_id=correlation_id,
            source_event_id=source_event_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=False)

    def _create(self, n: Notification, provenance: Provenance, *, dedupe: bool) -> Outcome:
        now = self._clock()
        existing = self._repo.get(n.id)
        if existing is not None:  # o mesmo evento de origem outra vez
            return Outcome(existing)
        if dedupe:
            open_one = self._repo.find_open(
                household_id=n.household_id,
                kind=n.kind,
                ref=n.ref,
                recipient_resident_id=n.recipient_resident_id,
            )
            if open_one is not None:
                if not open_one.is_expired(now):
                    return Outcome(open_one)
                # Vencido por tempo mas ainda `unread`/`read`: fecha-o antes de inserir o novo
                # (o índice único de deduplicação só admite um pedido aberto).
                self._repo.compare_and_set(
                    replace(open_one, status=NotificationStatus.expired), expected=open_one
                )
        if not self._repo.insert(n):  # perdeu a corrida com o mesmo evento
            return Outcome(self._repo.get(n.id))
        event = de.NotificationCreated(
            id=event_id_for("notification.created", n.id),
            ts=now,
            household_id=n.household_id,
            correlation_id=n.correlation_id,
            provenance=provenance,  # a do evento de origem
            data=de.NotificationCreatedData(
                notification_id=n.id,
                scope=n.scope,
                kind=n.kind,
                recipient_resident_id=n.recipient_resident_id,
            ),
        )
        return Outcome(n, (event,))

    # --- visibilidade ----------------------------------------------------------------------

    def _visible(self, n: Notification, resident_id: UUID, now: datetime) -> bool:
        role = self._directory.role_in(n.household_id, resident_id, now)
        if role is None:
            return False
        if role is not MembershipRole.tenant and n.kind not in _SENHORIO_PODE_VER:
            # Allow-list antes do âmbito: vale também para notificações pessoais endereçadas
            # ao senhorio (um `security_alert` pessoal continua escondido).
            return False
        if n.scope is NotificationScope.personal:
            return n.recipient_resident_id == resident_id
        return True

    def _get_visible(
        self, household_id: UUID, notification_id: UUID, resident_id: UUID, now: datetime
    ) -> Notification:
        n = self._repo.get(notification_id)
        # Outra casa é indistinguível de inexistente (o caminho da casa não dá acesso à de outrem).
        if n is None or n.household_id != household_id or not self._visible(n, resident_id, now):
            raise NotificationNotFoundError("notificação não encontrada")
        return n

    # --- resposta --------------------------------------------------------------------------

    def respond(
        self,
        notification_id: UUID,
        *,
        household_id: UUID,
        resident_id: UUID,
        action_id: str,
        target_resident_id: UUID | None = None,
    ) -> Outcome:
        """Regista a resposta e emite `notification.responded` (só quem ganha o CAS).

        Confirmações: é um VOTO (D-32); a notificação só fecha quando a regra B decide, e o
        evento sai por voto, com o `outcome`. Outros tipos: a primeira resposta vence.

        Concorrência: o CAS exige o estado e o n.º de votos lidos. Se perder, outro voto (ou
        outro estado) foi gravado entretanto: relê-se e reaplica-se a regra (que pode agora dar
        409 `already_responded`/`notification_expired`). Cada falha prova que outra escrita
        avançou, por isso o ciclo termina em, no máximo, um voto por elegível.
        """
        for _ in range(self._MAX_CAS_RETRIES):
            now = self._clock()
            n = self._get_visible(household_id, notification_id, resident_id, now)
            new = n.respond(resident_id, action_id, now, target_resident_id)  # erros do contrato
            if self._repo.compare_and_set(new, expected=n):
                return Outcome(new, (self._responded_event(n, new, now),))
        raise AlreadyRespondedError("resposta concorrente; tente de novo")

    # Cada falha do CAS = mais um voto ou estado gravado por outrem; há no máx. um voto por
    # elegível e poucos estados, por isso o limite nunca se atinge na prática.
    _MAX_CAS_RETRIES = 64

    @staticmethod
    def _responded_event(
        before: Notification, after: Notification, now: datetime
    ) -> de.NotificationResponded:
        vote = after.responses[-1] if after.responses else after.response
        assert vote is not None  # `respond` acrescenta sempre um voto ou fixa a resposta
        voting = after.kind is NotificationKind.confirmation_request
        return de.NotificationResponded(
            id=event_id_for("notification.responded", before.id, vote.resident_id),
            ts=now,
            household_id=before.household_id,
            correlation_id=before.correlation_id,
            provenance=Provenance(origin=before.origin, kind=ValueKind.measured),
            data=de.NotificationRespondedData(
                response=vote,
                ref=before.ref,
                outcome=after.outcome(now) if voting else None,
            ),
        )

    # --- leitura ---------------------------------------------------------------------------

    def mark_read(
        self, notification_id: UUID, *, household_id: UUID, resident_id: UUID
    ) -> NotificationView:
        """Recibo de leitura do residente; o estado partilhado só muda nas pessoais."""
        now = self._clock()
        n = self._get_visible(household_id, notification_id, resident_id, now)
        self._repo.mark_read(n.id, resident_id, now)
        if n.scope is NotificationScope.personal and n.status is NotificationStatus.unread:
            n.transition(NotificationStatus.read)
            self._repo.compare_and_set(replace(n, status=NotificationStatus.read), expected=n)
        return self.view(self._repo.get(n.id) or n, resident_id)

    def view(self, n: Notification, resident_id: UUID) -> NotificationView:
        """Vista para o residente (estado de leitura por residente nas notificações da casa)."""
        now = self._clock()
        view = NotificationView.for_resident(n, resident_id, now)
        if view.status is NotificationStatus.unread and self._repo.read_at(n.id, resident_id):
            return replace(view, status=NotificationStatus.read)
        return view

    def list_for(
        self,
        household_id: UUID,
        resident_id: UUID,
        *,
        status: NotificationStatus | None = None,
        scope: NotificationScope | None = None,
        limit: int = 50,
    ) -> list[NotificationView]:
        """Notificações visíveis ao residente, a mais recente primeiro."""
        if limit < 1:
            raise ValueError("limit tem de ser >= 1")
        now = self._clock()
        if self._directory.role_in(household_id, resident_id, now) is None:
            return []
        visible = [
            n
            for n in self._repo.list_household(household_id)
            if self._visible(n, resident_id, now) and (scope is None or n.scope is scope)
        ]
        visible.sort(key=lambda n: (n.created_at, str(n.id)), reverse=True)
        views = (self.view(n, resident_id) for n in visible)
        return [v for v in views if status is None or v.status is status][:limit]

    # --- expiração e entrega ---------------------------------------------------------------

    def expire_due(self) -> list[Notification]:
        """Passa a `expired` as abertas vencidas; devolve as que este varrimento expirou.

        Sem evento partilhado (a proposta `notification.expired` está em revisão).
        """
        now = self._clock()
        expired: list[Notification] = []
        for n in self._repo.open_due(now):
            n.transition(NotificationStatus.expired)
            new = replace(n, status=NotificationStatus.expired)
            if self._repo.compare_and_set(new, expected=n):
                expired.append(new)
        return expired

    def delivery(self, n: Notification, prefs: NotificationPreferences | None) -> Delivery:
        """Como entregar o push; a notificação persiste-se sempre."""
        local_time = self._clock().astimezone(self._tz).time()
        return delivery_for(n.kind, n.severity, prefs, local_time)
