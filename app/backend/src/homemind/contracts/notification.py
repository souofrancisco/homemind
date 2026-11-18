"""Notificações (a app substitui o Telegram, D-01). Dono: notifications (P3).

`Notification` é a entidade persistida (inclui quem pode responder); a API devolve
`NotificationView` (com `can_respond` já calculado, sem ids de quem respondeu).
As regras de resposta são puras: `Notification.respond` é a referência; a persistência tem
de aplicá-la com compare-and-set para que respostas simultâneas não se percam nem dupliquem.

REGRA B — «De quem é esta conta?» (`confirmation_request`) é uma VOTAÇÃO (D-32, decisão da
equipa de 17/11/2026). PREVALECE sobre qualquer implementação anterior baseada em «primeira
resposta vence»: quem fizer merge (pessoa ou agente) adapta o código de notifications (P3),
da UI (P5) e de billing a esta regra, não o contrário.
- Cada inquilino elegível vota uma vez: «É minha» (`mine`), «É de todos» (`everyone`),
  «Não sei» (`unknown`) ou «É de outra pessoa» (`other` + `target_resident_id`).
- Basta UM «É minha» para fechar: paga quem assumiu.
- Atribuir a outra pessoa exige que pelo menos metade dos elegíveis (arredondado para cima)
  vote `other` com o mesmo alvo; se o próprio assumir antes disso, fecha com ele.
- Votaram todos sem cumprir nenhuma regra, ou passaram 24 h (`expires_at`) → divide-se por
  todos (`everyone`).
`confirmation_outcome` é a fonte única desta regra. Compare-and-set dos votos: `UPDATE ...
WHERE id=? AND status IN ('unread','read') AND <n.º de votos> = <lido>`; se perder, reler e
tentar de novo. Os outros tipos mantêm uma só resposta (a primeira vence, 409 a seguir).
"""

from __future__ import annotations

from collections import Counter
from datetime import time
from enum import StrEnum
from math import ceil
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import (
    Cents,
    Confidence,
    ContractModel,
    LongText,
    Origin,
    ShortText,
    UtcDatetime,
    check_transition,
    replace,
)


class NotificationScope(StrEnum):
    personal = "personal"
    household = "household"


class NotificationKind(StrEnum):
    confirmation_request = "confirmation_request"
    budget_alert = "budget_alert"
    peak_alert = "peak_alert"
    forgotten_appliance = "forgotten_appliance"
    security_alert = "security_alert"
    comfort_alert = "comfort_alert"  # janela aberta com aquecimento (SAFE-01)
    presence_check = "presence_check"  # «estás em casa?» (presence)
    saving_tip = "saving_tip"
    automation_proposal = "automation_proposal"
    agent_action = "agent_action"
    info = "info"
    # «O que é este aparelho?» (ENERGY-04): da casa, a primeira resposta fecha (não é votação).
    appliance_identification = "appliance_identification"


class NotificationSeverity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class NotificationStatus(StrEnum):
    unread = "unread"
    read = "read"
    actioned = "actioned"
    expired = "expired"
    dismissed = "dismissed"


_OPEN = frozenset({NotificationStatus.unread, NotificationStatus.read})
NOTIFICATION_TRANSITIONS = {
    NotificationStatus.unread: frozenset(
        {
            NotificationStatus.read,
            NotificationStatus.actioned,
            NotificationStatus.expired,
            NotificationStatus.dismissed,
        }
    ),
    NotificationStatus.read: frozenset(
        {NotificationStatus.actioned, NotificationStatus.expired, NotificationStatus.dismissed}
    ),
    NotificationStatus.actioned: frozenset(),
    NotificationStatus.expired: frozenset(),
    NotificationStatus.dismissed: frozenset(),
}


class ConfirmationChoice(StrEnum):
    """`É minha | É de todos | Não sei | É de outra pessoa`. «Minha» é sempre de quem vota;
    `other` exige `target_resident_id` e só decide com metade dos votos (D-32)."""

    mine = "mine"
    everyone = "everyone"
    unknown = "unknown"
    other = "other"


class RefType(StrEnum):
    consumption_event = "consumption_event"
    bill = "bill"
    allocation = "allocation"
    budget = "budget"
    automation = "automation"
    agent_action = "agent_action"
    presence_check = "presence_check"  # `PresenceConfirmationRequest.id`
    safety_alert = "safety_alert"  # `SafetyAlert.id`
    contestation = "contestation"  # `Contestation.id` (BILL-06)
    rules_proposal = "rules_proposal"  # `RuleProposal.id` (HOUSE-04)
    appliance_identification = "appliance_identification"  # `ApplianceIdentificationRequest.id`


class NotificationRef(ContractModel):
    type: RefType
    id: UUID


class ActionStyle(StrEnum):
    primary = "primary"
    neutral = "neutral"
    danger = "danger"


class NotificationAction(ContractModel):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    label: Annotated[str, Field(min_length=1, max_length=40)]
    style: ActionStyle = ActionStyle.neutral


class NotificationResponse(ContractModel):
    """Quem respondeu (ou votou), com quê e quando. Fica gravada na notificação."""

    notification_id: UUID
    action_id: str
    resident_id: UUID
    responded_at: UtcDatetime
    target_resident_id: UUID | None = None  # só com `other`: a quem se atribui

    @model_validator(mode="after")
    def _target(self) -> Self:
        if (self.action_id == ConfirmationChoice.other) != (self.target_resident_id is not None):
            raise ValueError("target_resident_id exatamente com a ação `other`")
        if self.target_resident_id == self.resident_id:
            raise ValueError("atribuir a si próprio é `mine`")
        return self


class NotificationRespondIn(ContractModel):
    """Corpo de `POST /api/notifications/{id}/respond`."""

    action_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    target_resident_id: UUID | None = None


class ConfirmationVerdict(StrEnum):
    pending = "pending"  # ainda a votar
    self_claimed = "self_claimed"  # alguém disse «É minha»
    accusation_accepted = "accusation_accepted"  # ≥ metade atribuiu à mesma pessoa
    everyone = "everyone"  # todos votaram sem decisão, ou expirou: divide-se por todos


class ConfirmationOutcome(ContractModel):
    """Resultado da votação da regra B. `resident_id` = quem paga (só nos dois veredictos
    pessoais); `everyone` → conta comum; `pending` → nada a fazer ainda."""

    verdict: ConfirmationVerdict
    resident_id: UUID | None = None
    votes: Annotated[int, Field(strict=True, ge=0)]
    votes_needed: Annotated[int, Field(strict=True, ge=1)]  # para aceitar uma atribuição a outro

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        personal = self.verdict in (
            ConfirmationVerdict.self_claimed,
            ConfirmationVerdict.accusation_accepted,
        )
        if personal != (self.resident_id is not None):
            raise ValueError("resident_id exatamente nos veredictos pessoais")
        return self

    @property
    def decided(self) -> bool:
        return self.verdict is not ConfirmationVerdict.pending


def votes_needed(eligible: int) -> int:
    """Pelo menos metade dos elegíveis, arredondado para cima (4 → 2, 3 → 2, 5 → 3)."""
    return max(1, ceil(eligible / 2))


def confirmation_outcome(
    responses: list[NotificationResponse], eligible: list[UUID], *, expired: bool = False
) -> ConfirmationOutcome:
    """Fonte única da regra B (D-32). Os votos contam por ordem cronológica: decide a primeira
    condição cumprida. Votos repetidos ou de não elegíveis são erro (a notificação já os
    impede)."""
    voters = [r.resident_id for r in responses]
    if len(set(voters)) != len(voters) or not set(voters) <= set(eligible):
        raise ValueError("votos repetidos ou de quem não é elegível")
    needed = votes_needed(len(eligible))
    accusations: Counter[UUID] = Counter()
    base = {"votes": len(responses), "votes_needed": needed}
    for r in sorted(responses, key=lambda r: r.responded_at):
        if r.action_id == ConfirmationChoice.mine:
            return ConfirmationOutcome(
                verdict=ConfirmationVerdict.self_claimed, resident_id=r.resident_id, **base
            )
        if r.action_id == ConfirmationChoice.other:
            accusations[r.target_resident_id] += 1
            if accusations[r.target_resident_id] >= needed:
                return ConfirmationOutcome(
                    verdict=ConfirmationVerdict.accusation_accepted,
                    resident_id=r.target_resident_id,
                    **base,
                )
    if expired or len(responses) == len(eligible):
        return ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, **base)
    return ConfirmationOutcome(verdict=ConfirmationVerdict.pending, **base)


# Erros de resposta (→ HTTP nas rotas de P3).
class NotificationRespondError(ValueError):
    code = "invalid_request"


class AlreadyRespondedError(NotificationRespondError):
    code = "already_responded"  # 409


class NotificationExpiredError(NotificationRespondError):
    code = "notification_expired"  # 409


class NotAllowedToRespondError(NotificationRespondError):
    code = "forbidden_role"  # 403


class UnknownActionError(NotificationRespondError):
    code = "invalid_request"  # 400


class InvalidTargetError(NotificationRespondError):
    code = "invalid_request"  # 400: `other` sem alvo elegível, ou alvo noutra ação


class Notification(ContractModel):
    id: UUID
    household_id: UUID
    scope: NotificationScope
    recipient_resident_id: UUID | None = None  # pessoal: o destinatário
    # Quem pode responder (snapshot à criação). Inquilinos ativos para confirmações;
    # o senhorio nunca figura aqui.
    responder_ids: list[UUID] = []
    kind: NotificationKind
    severity: NotificationSeverity
    title: ShortText
    body: LongText
    origin: Origin  # `simulated` => a app mostra SIMULADO
    actions: Annotated[list[NotificationAction], Field(max_length=4)] = []
    status: NotificationStatus = NotificationStatus.unread
    expires_at: UtcDatetime | None = None
    ref: NotificationRef | None = None
    # Resposta que fechou a notificação (nas confirmações: o voto que decidiu).
    response: NotificationResponse | None = None
    # Só `confirmation_request`: todos os votos, por ordem (regra B, D-32).
    responses: list[NotificationResponse] = []
    correlation_id: UUID
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if (self.scope is NotificationScope.personal) != (self.recipient_resident_id is not None):
            raise ValueError("recipient_resident_id exatamente nas notificações pessoais")
        if self.scope is NotificationScope.personal and self.responder_ids not in (
            [],
            [self.recipient_resident_id],
        ):
            raise ValueError("numa notificação pessoal só o destinatário responde")
        ids = [a.id for a in self.actions]
        if len(set(ids)) != len(ids):
            raise ValueError("ações repetidas")
        if self.actions and not self.responder_ids:
            raise ValueError("ações sem quem possa responder")
        if self.kind is NotificationKind.confirmation_request and not self.expires_at:
            raise ValueError("pedido de confirmação exige expires_at")
        if self.kind is NotificationKind.presence_check and (
            self.scope is not NotificationScope.personal or not self.expires_at
        ):
            raise ValueError("«estás em casa?» é pessoal e exige expires_at")
        if (self.status is NotificationStatus.actioned) != (self.response is not None):
            raise ValueError("response exatamente quando o estado é actioned")
        if self.response and self.response.notification_id != self.id:
            raise ValueError("resposta de outra notificação")
        if self.expires_at and self.expires_at < self.created_at:
            raise ValueError("expires_at anterior a created_at")
        if self.kind is NotificationKind.confirmation_request:
            self._check_votes()
        elif self.responses:
            raise ValueError("votos só em pedidos de confirmação")
        return self

    def _check_votes(self) -> None:
        if any(r.notification_id != self.id for r in self.responses):
            raise ValueError("voto de outra notificação")
        targets = {r.target_resident_id for r in self.responses} - {None}
        if not targets <= set(self.responder_ids):
            raise ValueError("atribuição a quem não é elegível")
        decided = confirmation_outcome(self.responses, self.responder_ids).decided
        if decided != (self.status is NotificationStatus.actioned):
            raise ValueError("actioned exatamente quando a votação está decidida")
        if self.response is not None and self.response not in self.responses:
            raise ValueError("a resposta decisiva tem de ser um dos votos")

    def outcome(self, now: UtcDatetime) -> ConfirmationOutcome:
        """Estado da votação (só `confirmation_request`); expirada sem decisão → `everyone`."""
        if self.kind is not NotificationKind.confirmation_request:
            raise ValueError("só pedidos de confirmação têm votação")
        return confirmation_outcome(
            self.responses,
            self.responder_ids,
            expired=self.status is not NotificationStatus.actioned and self.is_expired(now),
        )

    def is_expired(self, now: UtcDatetime) -> bool:
        return self.status is NotificationStatus.expired or (
            self.status in _OPEN and self.expires_at is not None and now >= self.expires_at
        )

    def can_respond(self, resident_id: UUID, now: UtcDatetime) -> bool:
        return (
            bool(self.actions)
            and self.status in _OPEN
            and not self.is_expired(now)
            and resident_id in self.responder_ids
            and all(r.resident_id != resident_id for r in self.responses)  # um voto por pessoa
        )

    def transition(self, new: NotificationStatus) -> None:
        check_transition(NOTIFICATION_TRANSITIONS, self.status, new)

    def respond(
        self,
        resident_id: UUID,
        action_id: str,
        now: UtcDatetime,
        target_resident_id: UUID | None = None,
    ) -> Notification:
        """Confirmações: regista o voto e fecha (`actioned`) quando a regra B decide (D-32);
        votar duas vezes é 409. Outros tipos: a primeira resposta vence; repetir é 409."""
        if self.status is NotificationStatus.actioned:
            raise AlreadyRespondedError("já respondida")
        if self.is_expired(now):
            raise NotificationExpiredError("pedido expirado")
        if self.status is NotificationStatus.dismissed:
            raise AlreadyRespondedError("já dispensada")
        if resident_id not in self.responder_ids:
            raise NotAllowedToRespondError("sem permissão para responder")
        if action_id not in {a.id for a in self.actions}:
            raise UnknownActionError("ação desconhecida")
        voting = self.kind is NotificationKind.confirmation_request
        if (action_id == ConfirmationChoice.other) != (target_resident_id is not None):
            raise InvalidTargetError("`other` exige a pessoa; as outras ações não a aceitam")
        if target_resident_id is not None and (
            not voting
            or target_resident_id == resident_id
            or target_resident_id not in self.responder_ids
        ):
            raise InvalidTargetError("só se atribui a outro morador elegível")
        if any(r.resident_id == resident_id for r in self.responses):
            raise AlreadyRespondedError("já votou")
        response = NotificationResponse(
            notification_id=self.id,
            action_id=action_id,
            resident_id=resident_id,
            responded_at=now,
            target_resident_id=target_resident_id,
        )
        if not voting:
            return replace(self, status=NotificationStatus.actioned, response=response)
        votes = [*self.responses, response]
        if confirmation_outcome(votes, self.responder_ids).decided:
            return replace(
                self, status=NotificationStatus.actioned, response=response, responses=votes
            )
        return replace(self, responses=votes)


class ConfirmationRequest(ContractModel):
    """«De quem é esta conta?»: emitido por billing; P3 transforma-o em `Notification`."""

    consumption_event_id: UUID
    appliance_name: ShortText | None = None  # só para o texto; nunca um id externo
    likely_owner_resident_id: UUID | None = None
    match_confidence: Confidence | None = None
    estimated_cost_cents: Cents | None = None  # None: custo não estimável
    options: Annotated[list[ConfirmationChoice], Field(min_length=1)] = [
        ConfirmationChoice.mine,
        ConfirmationChoice.everyone,
        ConfirmationChoice.unknown,
        ConfirmationChoice.other,
    ]
    eligible_resident_ids: Annotated[list[UUID], Field(min_length=1)]
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len(set(self.options)) != len(self.options):
            raise ValueError("opções repetidas")
        if len(set(self.eligible_resident_ids)) != len(self.eligible_resident_ids):
            raise ValueError("elegíveis repetidos")
        if (self.likely_owner_resident_id is None) != (self.match_confidence is None):
            raise ValueError("dono provável e confiança têm de estar presentes em conjunto")
        if (
            self.likely_owner_resident_id is not None
            and self.likely_owner_resident_id not in self.eligible_resident_ids
        ):
            raise ValueError("dono provável tem de ser um inquilino elegível")
        return self


class QuietHours(ContractModel):
    start: time
    end: time  # pode ser < start (atravessa a meia-noite); horas locais da casa


class NotificationPreferences(ContractModel):
    resident_id: UUID
    quiet_hours: QuietHours | None = None
    disabled_kinds: list[NotificationKind] = []

    @model_validator(mode="after")
    def _critical_stays(self) -> Self:
        if NotificationKind.security_alert in self.disabled_kinds:
            raise ValueError("alertas de segurança não se desligam")
        return self


class ResponseView(ContractModel):
    action_id: str
    responded_at: UtcDatetime
    by_me: bool  # nunca o id de quem respondeu
    target_resident_id: UUID | None  # só em `other`: a pessoa a quem se atribui


class AccusationTally(ContractModel):
    """Votos «É de outra pessoa» por alvo (anónimos: só o número)."""

    target_resident_id: UUID
    votes: int


class VotingView(ContractModel):
    """Estado da votação da regra B (só `confirmation_request`)."""

    verdict: ConfirmationVerdict
    pays_me: bool  # decidido que paga quem está a ver (nunca o id de quem assumiu)
    votes: int
    eligible: int
    votes_needed: int
    accusations: list[AccusationTally]
    my_vote: ResponseView | None


def _response_view(r: NotificationResponse, resident_id: UUID) -> ResponseView:
    return ResponseView(
        action_id=r.action_id,
        responded_at=r.responded_at,
        by_me=r.resident_id == resident_id,
        target_resident_id=r.target_resident_id,
    )


class NotificationView(ContractModel):
    id: UUID
    scope: NotificationScope
    kind: NotificationKind
    severity: NotificationSeverity
    title: str
    body: str
    origin: Origin
    status: NotificationStatus
    actions: list[NotificationAction]
    can_respond: bool
    expires_at: UtcDatetime | None
    ref: NotificationRef | None
    response: ResponseView | None
    voting: VotingView | None
    created_at: UtcDatetime

    @classmethod
    def for_resident(cls, n: Notification, resident_id: UUID, now: UtcDatetime) -> NotificationView:
        resp = n.response
        return cls(
            id=n.id,
            scope=n.scope,
            kind=n.kind,
            severity=n.severity,
            title=n.title,
            body=n.body,
            origin=n.origin,
            status=NotificationStatus.expired if n.is_expired(now) else n.status,
            actions=n.actions,
            can_respond=n.can_respond(resident_id, now),
            expires_at=n.expires_at,
            ref=n.ref,
            response=_response_view(resp, resident_id) if resp else None,
            voting=_voting_view(n, resident_id, now)
            if n.kind is NotificationKind.confirmation_request
            else None,
            created_at=n.created_at,
        )


def _voting_view(n: Notification, resident_id: UUID, now: UtcDatetime) -> VotingView:
    out = n.outcome(now)
    tally = Counter(r.target_resident_id for r in n.responses if r.target_resident_id)
    mine = next((r for r in n.responses if r.resident_id == resident_id), None)
    return VotingView(
        verdict=out.verdict,
        pays_me=out.resident_id == resident_id,
        votes=out.votes,
        eligible=len(n.responder_ids),
        votes_needed=out.votes_needed,
        accusations=[
            AccusationTally(target_resident_id=t, votes=v) for t, v in sorted(tally.items())
        ],
        my_vote=_response_view(mine, resident_id) if mine else None,
    )
