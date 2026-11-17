"""Composição de notificações a partir de pedidos e alertas (funções puras).

Os textos são PT-PT e nunca incluem UUIDs, URLs nem identificadores de dispositivos. As regras de
resposta e de estado vivem no contrato (`contracts/notification.py`); aqui só se constrói a
`Notification`.
"""

from datetime import datetime
from uuid import UUID, uuid5

from homemind.contracts.common import Origin
from homemind.contracts.household import RoomKind
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
from homemind.contracts.presence import PRESENCE_CONFIRMATION_ACTIONS, UncertainReason
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


def notification_id_for_ref(kind: NotificationKind, ref_id: UUID, recipient: UUID | None) -> UUID:
    """Id derivado da coisa a que a notificação se refere (alerta, pedido, atribuição, recibo) e
    do destinatário (`None`: da casa): o mesmo alerta reentregue, mesmo com outro id de evento,
    repete o id e nunca duplica."""
    return uuid5(_NAMESPACE_P3, f"notification/{kind.value}/{ref_id}/{recipient or 'household'}")


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


def _tag(body: str, origin: Origin) -> str:
    return body + (_SIMULATED if origin is Origin.simulated else "")


# --- presença: «estás em casa?» ----------------------------------------------------------------

PRESENCE_LABELS = {"in": "Estou em casa", "out": "Estou fora"}
_PRESENCE_BODY = {
    UncertainReason.conflicting_cues: "Não temos a certeza se estás em casa. Podes confirmar?",
    UncertainReason.no_recent_cues: "Não temos sinais recentes teus. Estás em casa?",
}


def compose_presence_check(
    *,
    request_id: UUID,
    resident_id: UUID,
    reason: UncertainReason,
    expires_at: datetime,
    household_id: UUID,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Pergunta pessoal (nunca acusação): sem horas, sem aparelhos, sem nomes."""
    return Notification(
        id=notification_id_for_ref(NotificationKind.presence_check, request_id, resident_id),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        responder_ids=[resident_id],
        kind=NotificationKind.presence_check,
        severity=NotificationSeverity.info,
        title="Estás em casa?",
        body=_tag(_PRESENCE_BODY[reason], origin),
        origin=origin,
        actions=[
            NotificationAction(id=a, label=PRESENCE_LABELS[a])
            for a in PRESENCE_CONFIRMATION_ACTIONS
        ],
        expires_at=expires_at,
        ref=NotificationRef(type=RefType.presence_check, id=request_id),
        correlation_id=correlation_id,
        created_at=now,
    )


# --- segurança e conforto ----------------------------------------------------------------------


def _place(room: tuple[str, RoomKind] | None) -> str | None:
    """Nome da divisão só se for uma zona comum: o nome de um quarto pode identificar a pessoa."""
    return room[0] if room and room[1] is RoomKind.common else None


def compose_window_alert(
    *,
    alert_id: UUID,
    household_id: UUID,
    recipient_resident_id: UUID | None,
    room: tuple[str, RoomKind] | None,
    severity: NotificationSeverity,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Janela aberta com aquecimento: pessoal ao inquilino do quarto; senão, da casa. Sem
    botões (a ação sugerida só chega a `ProposedAction` quando existir executor)."""
    place = _place(room)
    if recipient_resident_id is not None:
        where = "A janela do teu quarto"
    elif place:
        where = f"A janela da zona «{place}»"
    else:
        where = "Uma janela"
    body = (
        f"{where} está aberta há mais de 5 minutos com o aquecimento ligado. "
        "Fecha a janela ou desliga o aquecimento para não desperdiçar energia."
    )
    personal = recipient_resident_id is not None
    return Notification(
        id=notification_id_for_ref(NotificationKind.comfort_alert, alert_id, recipient_resident_id),
        household_id=household_id,
        scope=NotificationScope.personal if personal else NotificationScope.household,
        recipient_resident_id=recipient_resident_id,
        kind=NotificationKind.comfort_alert,
        severity=severity,
        title="Janela aberta com o aquecimento ligado",
        body=_tag(body, origin),
        origin=origin,
        ref=NotificationRef(type=RefType.safety_alert, id=alert_id),
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_smoke_alert(
    *,
    alert_id: UUID,
    household_id: UUID,
    room: tuple[str, RoomKind] | None,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Fumo: crítico, da casa, sem botões. Nunca sugere cortes de energia."""
    place = _place(room)
    where = (
        f"Detetor de fumo em alarme na zona «{place}»." if place else "Detetor de fumo em alarme."
    )
    body = (
        f"{where} Se houver perigo, sai de casa e liga 112. "
        "Este sistema não substitui um detetor de fumo certificado."
    )
    return Notification(
        id=notification_id_for_ref(NotificationKind.security_alert, alert_id, None),
        household_id=household_id,
        scope=NotificationScope.household,
        kind=NotificationKind.security_alert,
        severity=NotificationSeverity.critical,
        title="Alarme de fumo",
        body=_tag(body, origin),
        origin=origin,
        ref=NotificationRef(type=RefType.safety_alert, id=alert_id),
        correlation_id=correlation_id,
        created_at=now,
    )


# --- faturação: informações pessoais -----------------------------------------------------------


def compose_attribution_info(
    *,
    attribution_id: UUID,
    consumption_event_id: UUID,
    household_id: UUID,
    resident_id: UUID,
    on_my_account: bool,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Resultado da votação «De quem é esta conta?», sem nomes de terceiros nem de aparelhos
    (P-18): só diz onde ficou o consumo."""
    if on_my_account:
        title = "Registado na tua conta"
        body = "Um consumo numa zona comum que estava por atribuir ficou registado na tua conta."
    else:
        title = "Dividido por todos"
        body = "Um consumo numa zona comum que estava por atribuir vai ser dividido por todos."
    return Notification(
        id=notification_id_for_ref(NotificationKind.info, attribution_id, resident_id),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        kind=NotificationKind.info,
        severity=NotificationSeverity.info,
        title=title,
        body=_tag(body, origin),
        origin=origin,
        ref=NotificationRef(type=RefType.consumption_event, id=consumption_event_id),
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_receipt_info(
    *,
    allocation_id: UUID,
    household_id: UUID,
    resident_id: UUID,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    return Notification(
        id=notification_id_for_ref(NotificationKind.info, allocation_id, resident_id),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        kind=NotificationKind.info,
        severity=NotificationSeverity.info,
        title="Recibo disponível",
        body=_tag("O teu recibo da fatura já está disponível.", origin),
        origin=origin,
        ref=NotificationRef(type=RefType.allocation, id=allocation_id),
        correlation_id=correlation_id,
        created_at=now,
    )
