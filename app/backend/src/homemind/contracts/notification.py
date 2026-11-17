"""Notificações (a app substitui o Telegram, D-01). Dono: notifications (P3).

`Notification` é a entidade persistida (inclui quem pode responder); a API devolve
`NotificationView` (com `can_respond` já calculado, sem ids de terceiros).
As regras de resposta são puras: `Notification.respond` é a referência; a persistência tem
de aplicá-la com compare-and-set (`UPDATE ... WHERE status IN ('unread','read')`, 1 linha
afetada) para que respostas simultâneas tenham um só vencedor.
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import (
    Cents,
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
    """`É minha | É de todos | Não sei`. «Minha» é sempre de quem responde, nunca de terceiros."""

    mine = "mine"
    everyone = "everyone"
    unknown = "unknown"


class RefType(StrEnum):
    consumption_event = "consumption_event"
    bill = "bill"
    allocation = "allocation"
    budget = "budget"
    automation = "automation"
    agent_action = "agent_action"
    presence_check = "presence_check"  # `PresenceConfirmationRequest.id`
    safety_alert = "safety_alert"  # `SafetyAlert.id`


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
    """Quem respondeu, com quê e quando. Fica gravada na notificação."""

    notification_id: UUID
    action_id: str
    resident_id: UUID
    responded_at: UtcDatetime


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
    response: NotificationResponse | None = None
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
        return self

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
        )

    def transition(self, new: NotificationStatus) -> None:
        check_transition(NOTIFICATION_TRANSITIONS, self.status, new)

    def respond(self, resident_id: UUID, action_id: str, now: UtcDatetime) -> Notification:
        """Primeira resposta válida vence; repetir é 409. Devolve a notificação `actioned`."""
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
        response = NotificationResponse(
            notification_id=self.id, action_id=action_id, resident_id=resident_id, responded_at=now
        )
        return replace(self, status=NotificationStatus.actioned, response=response)


class ConfirmationRequest(ContractModel):
    """«De quem é esta conta?»: emitido por billing; P3 transforma-o em `Notification`."""

    consumption_event_id: UUID
    appliance_name: ShortText | None = None  # só para o texto; nunca um id externo
    estimated_cost_cents: Cents | None = None  # None: custo não estimável
    options: Annotated[list[ConfirmationChoice], Field(min_length=1)] = [
        ConfirmationChoice.mine,
        ConfirmationChoice.everyone,
        ConfirmationChoice.unknown,
    ]
    eligible_resident_ids: Annotated[list[UUID], Field(min_length=1)]
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len(set(self.options)) != len(self.options):
            raise ValueError("opções repetidas")
        if len(set(self.eligible_resident_ids)) != len(self.eligible_resident_ids):
            raise ValueError("elegíveis repetidos")
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
            response=ResponseView(
                action_id=resp.action_id,
                responded_at=resp.responded_at,
                by_me=resp.resident_id == resident_id,
            )
            if resp
            else None,
            created_at=n.created_at,
        )
