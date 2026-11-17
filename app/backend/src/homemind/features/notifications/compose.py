"""Composição de notificações a partir de pedidos e alertas (funções puras).

Os textos são PT-PT e nunca incluem UUIDs, URLs nem identificadores de dispositivos. As regras de
resposta e de estado vivem no contrato (`contracts/notification.py`); aqui só se constrói a
`Notification`.
"""

from datetime import datetime
from uuid import UUID, uuid5

from homemind.contracts.common import Origin
from homemind.contracts.notification import (
    ActionStyle,
    ConfirmationRequest,
    Notification,
    NotificationAction,
    NotificationKind,
    NotificationRef,
    NotificationScope,
    NotificationSeverity,
    RefType,
)
from homemind.features.notifications.text import format_eur

# Espaço de nomes dos ids determinísticos da P3 (idempotência: mesmo evento, mesmo id).
_NAMESPACE_P3 = UUID("8c3f5b7e-1d24-4e6a-9b0c-5a1e7d3c2f40")

CONFIRMATION_LABELS = {
    "mine": "É minha",
    "everyone": "É de todos",
    "unknown": "Não sei",
    "other": "É de outra pessoa",  # a app pede a pessoa e envia `target_resident_id`
}

_SIMULATED = " (SIMULADO)"


def notification_id_for(source_event_id: UUID, kind: NotificationKind) -> UUID:
    """Id da notificação derivado do evento de origem: repetir o evento repete o id."""
    return uuid5(_NAMESPACE_P3, f"notification/{kind.value}/{source_event_id}")


def event_id_for(event_type: str, notification_id: UUID, resident_id: UUID | None = None) -> UUID:
    """Id do evento de seguimento (`notification.created`/`notification.responded`).

    `notification.responded` sai por voto: o id inclui quem votou (um voto por pessoa)."""
    suffix = f"/{resident_id}" if resident_id else ""
    return uuid5(_NAMESPACE_P3, f"event/{event_type}/{notification_id}{suffix}")


def compose_confirmation(
    req: ConfirmationRequest,
    *,
    household_id: UUID,
    responder_ids: list[UUID],
    origin: Origin,
    correlation_id: UUID,
    source_event_id: UUID,
    now: datetime,
) -> Notification:
    """«De quem é esta conta?»: notificação da casa, só para quem pode responder."""
    subject = f"O {req.appliance_name}" if req.appliance_name else "Um aparelho"
    body = f"{subject} está ligado numa zona comum"
    if req.estimated_cost_cents is not None:
        body += f", cerca de {format_eur(req.estimated_cost_cents)} estimados"
    if origin is Origin.simulated:
        body += _SIMULATED
    body += "."
    actions = [
        NotificationAction(
            id=choice.value,
            label=CONFIRMATION_LABELS[choice.value],
            style=ActionStyle.primary if choice.value == "mine" else ActionStyle.neutral,
        )
        for choice in req.options
    ]
    return Notification(
        id=notification_id_for(source_event_id, NotificationKind.confirmation_request),
        household_id=household_id,
        scope=NotificationScope.household,
        responder_ids=list(responder_ids),
        kind=NotificationKind.confirmation_request,
        severity=NotificationSeverity.info,
        title="De quem é esta conta?",
        body=body,
        origin=origin,
        actions=actions,
        expires_at=req.expires_at,
        ref=NotificationRef(type=RefType.consumption_event, id=req.consumption_event_id),
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_budget_alert(
    *,
    household_id: UUID,
    resident_id: UUID,
    budget_id: UUID,
    pct: int,
    spent_cents: int,
    limit_cents: int | None,
    forecast_cents: int | None,
    origin: Origin,
    correlation_id: UUID,
    source_event_id: UUID,
    now: datetime,
) -> Notification:
    """Aviso de orçamento: pessoal, informativo e sem ações."""
    spent = format_eur(spent_cents)
    if limit_cents is not None:
        body = f"Já gastaste {spent} dos teus {format_eur(limit_cents)} ({pct} %)."
    else:
        body = f"Já gastaste {spent} ({pct} %)."
    if forecast_cents is not None:
        body += f" Ao ritmo atual chegas aos {format_eur(forecast_cents)}."
    if origin is Origin.simulated:
        body += _SIMULATED
    return Notification(
        id=notification_id_for(source_event_id, NotificationKind.budget_alert),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        kind=NotificationKind.budget_alert,
        severity=NotificationSeverity.info if pct < 80 else NotificationSeverity.warning,
        title=f"Orçamento a {pct} %",
        body=body,
        origin=origin,
        ref=NotificationRef(type=RefType.budget, id=budget_id),
        correlation_id=correlation_id,
        created_at=now,
    )
