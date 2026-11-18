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
from homemind.contracts.agent import ProposedAction
from homemind.contracts.billing import (
    Attribution,
    AttributionStatus,
    AttributionTarget,
    Contestation,
    ContestationStatus,
)
from homemind.contracts.common import Provenance, ValueKind, replace
from homemind.contracts.energy import ApplianceIdentificationRequest
from homemind.contracts.household import MembershipRole, RoomKind
from homemind.contracts.notification import (
    AlreadyRespondedError,
    ConfirmationRequest,
    Notification,
    NotificationKind,
    NotificationPreferences,
    NotificationRef,
    NotificationScope,
    NotificationStatus,
    NotificationView,
    RefType,
)
from homemind.contracts.presence import PresenceConfirmationRequest
from homemind.contracts.safety import SafetyAlert, SafetyAlertKind, SafetyAlertStatus
from homemind.features.notifications.compose import (
    compose_agent_action,
    compose_anomaly_alert,
    compose_appliance_identification,
    compose_attribution_info,
    compose_budget_alert,
    compose_cold_room,
    compose_confirmation,
    compose_contestation_decided,
    compose_contestation_opened,
    compose_peak_alert,
    compose_presence_check,
    compose_receipt_info,
    compose_smoke_alert,
    compose_window_alert,
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

    def on_peak_alert(
        self,
        alert: de.AlertRaisedData,
        *,
        source_event_id: UUID,
        ts: datetime,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`alerts.alert_raised` com `kind=peak` -> aviso da casa (ALERT-03).

        Sem potência ou início do episódio não se escreve o aviso (não se inventam números).
        A idempotência vem do id derivado do evento (o detetor já avisa uma vez por incidente).
        """
        if alert.kind is not de.AlertKind.peak or alert.power_w is None or alert.since is None:
            return Outcome(None)
        room = self._directory.room(household_id, alert.room_id) if alert.room_id else None
        name = (
            self._directory.appliance_name(household_id, alert.appliance_id)
            if alert.appliance_id and room
            else None
        )
        n = compose_peak_alert(
            source_event_id=source_event_id,
            household_id=household_id,
            room=room,
            appliance_name=name,
            power_w=alert.power_w,
            minutes=int((ts - alert.since).total_seconds() // 60),
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=self._clock(),
        )
        return self._create(n, provenance, dedupe=False)

    def on_anomaly_alert(
        self,
        alert: de.AlertRaisedData,
        *,
        source_event_id: UUID,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`alerts.alert_raised` com `kind=anomaly` -> aviso da casa (ALERT-03, gasto anormal).

        Sem os números (gasto e habitual) ou sem zona comum conhecida não se escreve o aviso.
        Id derivado do evento (o detetor já avisa uma vez por tomada e dia).
        """
        if (
            alert.kind is not de.AlertKind.anomaly
            or alert.energy_wh is None
            or alert.baseline_wh is None
            or alert.room_id is None
        ):
            return Outcome(None)
        n = compose_anomaly_alert(
            source_event_id=source_event_id,
            household_id=household_id,
            room=self._directory.room(household_id, alert.room_id),
            energy_wh=alert.energy_wh,
            baseline_wh=alert.baseline_wh,
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=self._clock(),
        )
        if n is None:
            return Outcome(None)
        return self._create(n, provenance, dedupe=False)

    def on_action_proposed(
        self,
        action: ProposedAction,
        *,
        source_event_id: UUID,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`agent.action_proposed` -> «Ação por confirmar» pessoal, só a um inquilino ativo.

        Sem botões: confirma-se na rota do agente. Proposta já caducada: nada (perguntar agora
        seria ruído). Id derivado do evento de origem (reentrega não duplica).
        """
        now = self._clock()
        if action.expires_at <= now:
            return Outcome(None)
        resident_id = action.proposed_for_resident_id
        if self._directory.role_in(household_id, resident_id, now) != MembershipRole.tenant:
            return Outcome(None)
        n = compose_agent_action(
            source_event_id=source_event_id,
            action_id=action.id,
            household_id=household_id,
            resident_id=resident_id,
            rationale=action.rationale,
            expires_at=action.expires_at,
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=False)

    def on_cold_room(
        self,
        d: de.ColdRoomData,
        *,
        source_event_id: UUID,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`alerts.cold_room` (ALERT-06) -> aviso privado ao morador do quarto (nunca senhorio)."""
        now = self._clock()
        if self._directory.role_in(household_id, d.resident_id, now) is not MembershipRole.tenant:
            return Outcome(None)
        n = compose_cold_room(
            household_id=household_id,
            resident_id=d.resident_id,
            cold_nights=d.cold_nights,
            window_nights=d.window_nights,
            threshold_c=d.threshold_c,
            coldest_night_c=d.coldest_night_c,
            allowance_left_wh=d.allowance_left_wh,
            origin=provenance.origin,
            correlation_id=correlation_id,
            source_event_id=source_event_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=False)

    def on_presence_check(
        self,
        req: PresenceConfirmationRequest,
        *,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`presence.confirmation_needed` -> «estás em casa?» pessoal, só para um inquilino ativo.

        Deduplica por pedido aberto; a resposta volta em `notification.responded`
        (`ref.type = presence_check`) e é a presença que a trata.
        """
        now = self._clock()
        if req.expires_at <= now:
            return Outcome(None)  # já caducou: perguntar agora seria ruído
        if self._directory.role_in(household_id, req.resident_id, now) != MembershipRole.tenant:
            return Outcome(None)
        n = compose_presence_check(
            request_id=req.id,
            resident_id=req.resident_id,
            reason=req.reason,
            expires_at=req.expires_at,
            household_id=household_id,
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=True)

    def on_identification_needed(
        self,
        req: ApplianceIdentificationRequest,
        *,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`energy.identification_needed` (ENERGY-04) -> «O que é este aparelho?» da casa.

        Respondem os inquilinos ativos (nunca o senhorio, que também não a vê: allow-list); a
        primeira resposta fecha e volta em `notification.responded` (`ref.type =
        appliance_identification`), que é a energia que trata. Id derivado do pedido.
        """
        now = self._clock()
        if req.expires_at <= now:
            return Outcome(None)  # já caducou: perguntar agora seria ruído
        responders = self._directory.tenants(household_id, now)
        if not responders:
            return Outcome(None)
        n = compose_appliance_identification(
            req,
            household_id=household_id,
            responder_ids=responders,
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=False)

    def on_safety_alert(
        self,
        alert: SafetyAlert,
        *,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`safety.alert_raised`: ativo -> aviso; resolvido -> as notificações abertas do alerta
        passam a `expired` (sem evento: a notificação só deixou de ser relevante).

        O senhorio continua sem ver estes tipos (allow-list); `notify_landlord` fica pendente.
        """
        now = self._clock()
        ref = NotificationRef(type=RefType.safety_alert, id=alert.id)
        if alert.status is SafetyAlertStatus.resolved:
            self._expire_open(household_id, ref)
            return Outcome(None)
        room = self._directory.room(household_id, alert.room_id) if alert.room_id else None
        if alert.kind is SafetyAlertKind.smoke:
            n = compose_smoke_alert(
                alert_id=alert.id,
                household_id=household_id,
                room=room,
                origin=provenance.origin,
                correlation_id=correlation_id,
                now=now,
            )
        else:
            tenants = (
                self._directory.room_tenants(household_id, alert.room_id, now)
                if alert.room_id and room and room[1] is RoomKind.bedroom
                else []
            )
            n = compose_window_alert(
                alert_id=alert.id,
                household_id=household_id,
                recipient_resident_id=tenants[0] if tenants else None,
                room=room,
                severity=alert.severity,
                origin=provenance.origin,
                correlation_id=correlation_id,
                now=now,
            )
        return self._create(n, provenance, dedupe=False)

    def on_attribution_changed(
        self,
        attribution: Attribution,
        *,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`billing.attribution_changed` -> informação pessoal sobre um «De quem é esta conta?».

        Só para atribuições ativas de consumos que a P3 perguntou (existe um pedido com esse
        `consumption_event_id`); as outras são da P4 e ignoram-se. Nunca é da casa (o senhorio
        vê `info`) e nunca nomeia ninguém: «registado na tua conta» ao pagador; «dividido por
        todos» a quem votou.
        """
        if attribution.status is not AttributionStatus.active:
            return Outcome(None)
        requests = self._repo.find_by_ref(
            household_id=household_id,
            ref=NotificationRef(
                type=RefType.consumption_event, id=attribution.consumption_event_id
            ),
            kind=NotificationKind.confirmation_request,
        )
        if not requests:
            return Outcome(None)
        if attribution.target_type is AttributionTarget.resident:
            assert attribution.target_resident_id is not None  # invariante do contrato
            recipients = [attribution.target_resident_id]
        else:  # comum: quem votou foi quem foi perguntado e participou
            recipients = list(dict.fromkeys(r.resident_id for n in requests for r in n.responses))
        now = self._clock()
        created: list[Notification] = []
        events: list[de.DomainEvent] = []
        for resident_id in recipients:
            if self._directory.role_in(household_id, resident_id, now) != MembershipRole.tenant:
                continue  # saiu da casa (ou nunca foi inquilino): nada
            out = self._create(
                compose_attribution_info(
                    attribution_id=attribution.id,
                    consumption_event_id=attribution.consumption_event_id,
                    household_id=household_id,
                    resident_id=resident_id,
                    on_my_account=attribution.target_type is AttributionTarget.resident,
                    origin=provenance.origin,
                    correlation_id=correlation_id,
                    now=now,
                ),
                provenance,
                dedupe=False,
            )
            if out.notification is not None:
                created.append(out.notification)
            events += out.events
        return Outcome(created[0] if created else None, tuple(events))

    def on_allocation_published(
        self,
        data: de.AllocationPublished,
        *,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`billing.allocation_published` -> «o teu recibo está disponível» (pessoal, info)."""
        now = self._clock()
        if self._directory.role_in(household_id, data.resident_id, now) != MembershipRole.tenant:
            return Outcome(None)
        n = compose_receipt_info(
            allocation_id=data.allocation_id,
            household_id=household_id,
            resident_id=data.resident_id,
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=False)

    def on_contestation(
        self,
        c: Contestation,
        *,
        household_id: UUID,
        correlation_id: UUID,
        provenance: Provenance,
    ) -> Outcome:
        """`billing.contestation_changed` (BILL-06): aberta -> aviso aos senhorios (sem o motivo
        nem o consumo); decidida -> aviso pessoal a quem contestou, com a justificação."""
        now = self._clock()
        if c.status is ContestationStatus.open:
            events: list[de.DomainEvent] = []
            first = None
            for landlord in self._directory.landlords(household_id, now):
                n = compose_contestation_opened(
                    contestation_id=c.id,
                    household_id=household_id,
                    landlord_id=landlord,
                    origin=provenance.origin,
                    correlation_id=correlation_id,
                    now=now,
                )
                out = self._create(n, provenance, dedupe=False)
                first = first or out.notification
                events += out.events
            return Outcome(first, tuple(events))
        if self._directory.role_in(household_id, c.resident_id, now) is not MembershipRole.tenant:
            return Outcome(None)
        n = compose_contestation_decided(
            contestation_id=c.id,
            household_id=household_id,
            resident_id=c.resident_id,
            accepted=c.status is ContestationStatus.accepted,
            resolution=c.resolution or "",
            before_cents=c.before_cents,
            after_cents=c.after_cents,
            origin=provenance.origin,
            correlation_id=correlation_id,
            now=now,
        )
        return self._create(n, provenance, dedupe=False)

    def _expire_open(self, household_id: UUID, ref: NotificationRef) -> None:
        """Passa a `expired` as notificações abertas com essa referência (CAS; relê se perder)."""
        for _ in range(3):
            pending = self._repo.find_by_ref(household_id=household_id, ref=ref, open_only=True)
            if not pending:
                return
            for n in pending:
                n.transition(NotificationStatus.expired)
                self._repo.compare_and_set(
                    replace(n, status=NotificationStatus.expired), expected=n
                )

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
