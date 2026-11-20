"""Composição de notificações a partir de pedidos e alertas (funções puras).

Os textos são PT-PT e nunca incluem UUIDs, URLs nem identificadores de dispositivos. As regras de
resposta e de estado vivem no contrato (`contracts/notification.py`); aqui só se constrói a
`Notification`.
"""

import unicodedata
from datetime import date, datetime, timedelta
from uuid import UUID, uuid5

from homemind.contracts.agent import AutomationRule, AutomationStatus, TriggerKind
from homemind.contracts.common import Origin
from homemind.contracts.energy import (
    APPLIANCE_IDENTIFICATION_ACTIONS,
    ApplianceIdentificationRequest,
)
from homemind.contracts.household import CommonAreaRule, HouseholdPolicy, RoomKind
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
from homemind.features.notifications.text import format_eur, format_kw, format_kwh

# Espaço de nomes dos ids determinísticos da P3 (idempotência: mesmo evento, mesmo id).
_NAMESPACE_P3 = UUID("8c3f5b7e-1d24-4e6a-9b0c-5a1e7d3c2f40")

CONFIRMATION_LABELS = {
    "mine": "É minha",
    "everyone": "É de todos",  # só em notificações antigas (D-32: já não se oferece)
    "unknown": "Não sei",
    "other": "Escolher responsável(eis)",  # a app pede as pessoas: `target_resident_ids`
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
    likely_owner_name: str | None = None,
) -> Notification:
    """«De quem é esta conta?»: notificação da casa, só para quem pode responder."""
    subject = f"O {req.appliance_name}" if req.appliance_name else "Um aparelho"
    body = f"{subject} está ligado numa zona comum"
    if req.estimated_cost_cents is not None:
        body += f", cerca de {format_eur(req.estimated_cost_cents)} estimados"
    if req.likely_owner_resident_id is not None and req.match_confidence is not None:
        confidence = round(req.match_confidence * 100)
        has_owner_in_name = bool(
            likely_owner_name
            and _normalise_name(likely_owner_name) in _normalise_name(req.appliance_name or "")
        )
        if likely_owner_name:
            if has_owner_in_name:
                body += f". Aparelho identificado a {confidence} %"
            else:
                body += (
                    f". Parece ser do {likely_owner_name} (aparelho identificado a {confidence} %);"
                    " confirma"
                )
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


def _normalise_name(value: str) -> str:
    """Normalização para comparar nomes sem distinção de maiúsculas ou acentos."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


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


def compose_cold_room(
    *,
    household_id: UUID,
    resident_id: UUID,
    cold_nights: int,
    window_nights: int,
    threshold_c: float,
    coldest_night_c: float,
    allowance_left_wh: int | None = None,
    origin: Origin,
    correlation_id: UUID,
    source_event_id: UUID,
    now: datetime,
) -> Notification:
    """Quarto frio (ALERT-06): pessoal, privado e sem ações. Diz o plafond solidário que o
    quarto ainda tem no mês, só se billing o calculou (`None`: sem plafond, não se promete)."""
    t, c = f"{threshold_c:.0f}".replace(".", ","), f"{coldest_night_c:.1f}".replace(".", ",")
    body = (
        f"O teu quarto esteve abaixo de {t} °C em {cold_nights} das últimas {window_nights}"
        f" noites (a mais fria em média: {c} °C). Não deixes de aquecer por causa da conta"
    )
    if allowance_left_wh is None:
        body += "; se precisares, fala com a casa sobre o plafond solidário."
    elif allowance_left_wh > 0:
        kwh = f"{allowance_left_wh / 1000:.1f}".replace(".", ",")
        body += (
            f": este mês o teu quarto ainda tem {kwh} kWh do plafond solidário, e esse"
            " aquecimento é pago por todos."
        )
    else:
        body += (
            ": o plafond solidário do teu quarto deste mês já foi usado; se precisares,"
            " fala com a casa."
        )
    return Notification(
        id=notification_id_for(source_event_id, NotificationKind.comfort_alert),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        kind=NotificationKind.comfort_alert,
        severity=NotificationSeverity.info,
        title="O teu quarto tem estado frio",
        body=_tag(body, origin),
        origin=origin,
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_agent_action(
    *,
    source_event_id: UUID,
    action_id: UUID,
    household_id: UUID,
    resident_id: UUID,
    rationale: str,
    expires_at: datetime,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Ação proposta pelo assistente: pessoal e SEM botões (a confirmação é na rota do agente,
    `POST …/agent/actions/{id}/confirm|reject`; a UI usa o `ref`). Nada é executado aqui."""
    return Notification(
        id=notification_id_for(source_event_id, NotificationKind.agent_action),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        kind=NotificationKind.agent_action,
        severity=NotificationSeverity.info,
        title="Ação por confirmar",
        body=_tag(f"{rationale} Nada é executado sem a tua confirmação.", origin),
        origin=origin,
        expires_at=expires_at,
        ref=NotificationRef(type=RefType.agent_action, id=action_id),
        correlation_id=correlation_id,
        created_at=now,
    )


# Prazo da votação das regras da casa (SAFE-04). O serviço das automações guarda o mesmo valor
# (`features/automations`); aqui duplica-se porque uma feature não importa outra.
AUTOMATION_VOTE_WINDOW = timedelta(hours=24)


def _trigger_text(rule: AutomationRule) -> str:
    t = rule.trigger
    if t.kind is TriggerKind.power_above:
        return f"quando a potência passar de {t.threshold_w:g} W durante {t.duration_s} s"
    return "quando mudar quem está em casa"


def compose_automation_proposal(
    *,
    rule: AutomationRule,
    source_event_id: UUID,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Regra da casa proposta (SAFE-04): da casa (só os inquilinos a veem), sem botões; vota-se na
    rota das automações (a UI usa o `ref`). Nada é executado enquanto a regra não for aprovada.
    Regra `disabled` = pedido de reativação. O id deriva do evento de origem (uma por ronda)."""
    reactivation = rule.status is AutomationStatus.disabled
    what = "a reativação da regra" if reactivation else "a regra"
    return Notification(
        id=notification_id_for_ref(NotificationKind.automation_proposal, source_event_id, None),
        household_id=rule.household_id,
        scope=NotificationScope.household,
        kind=NotificationKind.automation_proposal,
        severity=NotificationSeverity.info,
        title="Reativar uma regra da casa: vota"
        if reactivation
        else "Nova regra da casa para votar",
        body=_tag(
            f"Foi proposta {what} «{rule.name}»: desligar uma tomada {_trigger_text(rule)}. "
            "Só passa a valer se a maioria dos moradores votar a favor em 24 h; "
            "até lá nada é executado.",
            origin,
        ),
        origin=origin,
        expires_at=now + AUTOMATION_VOTE_WINDOW,
        ref=NotificationRef(type=RefType.automation, id=rule.id),
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


# --- energia: «O que é este aparelho?» (ENERGY-04) ---------------------------------------------

IDENTIFICATION_LABELS = {"mine": "É meu", "household": "É da casa", "ignore": "Ignorar"}


def compose_appliance_identification(
    req: ApplianceIdentificationRequest,
    *,
    household_id: UUID,
    responder_ids: list[UUID],
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Pergunta da casa aos inquilinos ativos: potência arredondada e hora local aproximada,
    sem nomes de pessoas nem divisões. A primeira resposta fecha (não é votação)."""
    body = (
        f"Um aparelho de ~{req.approx_power_w} W liga muitas vezes por volta das"
        f" {req.hour_local}h. O que é?"
    )
    return Notification(
        id=notification_id_for_ref(NotificationKind.appliance_identification, req.id, None),
        household_id=household_id,
        scope=NotificationScope.household,
        responder_ids=list(responder_ids),
        kind=NotificationKind.appliance_identification,
        severity=NotificationSeverity.info,
        title="O que é este aparelho?",
        body=_tag(body, origin),
        origin=origin,
        actions=[
            NotificationAction(
                id=a,
                label=IDENTIFICATION_LABELS[a],
                style=ActionStyle.primary if a == "mine" else ActionStyle.neutral,
            )
            for a in APPLIANCE_IDENTIFICATION_ACTIONS
        ],
        expires_at=req.expires_at,
        ref=NotificationRef(type=RefType.appliance_identification, id=req.id),
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


def compose_peak_alert(
    *,
    source_event_id: UUID,
    household_id: UUID,
    room: tuple[str, RoomKind] | None,
    appliance_name: str | None,
    power_w: float,
    minutes: int,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification:
    """Pico numa zona comum (ALERT-03): da casa, aviso, sem botões. Sem zona comum conhecida
    diz «por identificar» e não sugere aparelho nem divisão."""
    place = _place(room)
    if place:
        title = f"Pico de consumo na zona «{place}»"
        body = f"A zona «{place}» está a gastar {format_kw(power_w)} há {minutes} min."
        if appliance_name:
            body += f" Provavelmente: {appliance_name}."
    else:
        title = "Pico de consumo por identificar"
        body = (
            f"Uma tomada está a gastar {format_kw(power_w)} há {minutes} min. "
            "Ainda não sabemos em que zona está."
        )
    return Notification(
        id=notification_id_for(source_event_id, NotificationKind.peak_alert),
        household_id=household_id,
        scope=NotificationScope.household,
        kind=NotificationKind.peak_alert,
        severity=NotificationSeverity.warning,
        title=title,
        body=_tag(body, origin),
        origin=origin,
        ref=None,
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_anomaly_alert(
    *,
    source_event_id: UUID,
    household_id: UUID,
    room: tuple[str, RoomKind] | None,
    energy_wh: int,
    baseline_wh: int,
    origin: Origin,
    correlation_id: UUID,
    now: datetime,
) -> Notification | None:
    """Gasto anormal numa zona comum (ALERT-03): da casa, informação, sem botões. Só com zona
    comum conhecida (o detetor nunca avisa de outras); não sugere aparelho nem pessoa."""
    place = _place(room)
    if place is None:
        return None
    return Notification(
        id=notification_id_for(source_event_id, NotificationKind.peak_alert),
        household_id=household_id,
        scope=NotificationScope.household,
        kind=NotificationKind.peak_alert,
        severity=NotificationSeverity.warning,
        title=f"Gasto fora do habitual na zona «{place}»",
        body=_tag(
            f"Hoje a zona «{place}» já gastou {format_kwh(energy_wh)}; num dia habitual gasta "
            f"{format_kwh(baseline_wh)}. Vale a pena ver se ficou algo ligado.",
            origin,
        ),
        origin=origin,
        ref=None,
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


# --- contestações (BILL-06) ---------------------------------------------------------------------


def compose_contestation_opened(
    *, contestation_id: UUID, household_id: UUID, landlord_id: UUID, origin: Origin,
    correlation_id: UUID, now: datetime,
) -> Notification:  # fmt: skip
    """Ao senhorio: só que há uma contestação (o detalhe, por quarto, está na lista)."""
    return Notification(
        id=notification_id_for_ref(NotificationKind.info, contestation_id, landlord_id),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=landlord_id,
        kind=NotificationKind.info,
        severity=NotificationSeverity.warning,
        title="Nova contestação de um recibo",
        body=_tag("Um morador contestou a sua parcela da fatura. Decide com justificação.", origin),
        origin=origin,
        ref=NotificationRef(type=RefType.contestation, id=contestation_id),
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_contestation_decided(
    *, contestation_id: UUID, household_id: UUID, resident_id: UUID, accepted: bool,
    resolution: str, before_cents: int | None, after_cents: int | None, origin: Origin,
    correlation_id: UUID, now: datetime,
) -> Notification:  # fmt: skip
    """A quem contestou: a decisão, a justificação e, se aceite, o antes/depois da parcela."""
    body = f"Justificação: {resolution}"
    if accepted and before_cents is not None and after_cents is not None:
        body = (
            f"A fatura foi reemitida: a tua parcela passou de {format_eur(before_cents)}"
            f" para {format_eur(after_cents)}. " + body
        )
    return Notification(
        id=notification_id_for_ref(NotificationKind.info, contestation_id, resident_id),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=resident_id,
        kind=NotificationKind.info,
        severity=NotificationSeverity.info,
        title="Contestação aceite" if accepted else "Contestação rejeitada",
        body=_tag(body, origin),
        origin=origin,
        ref=NotificationRef(type=RefType.contestation, id=contestation_id),
        correlation_id=correlation_id,
        created_at=now,
    )


# --- regras da casa (HOUSE-04) -----------------------------------------------------------------

_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)  # fmt: skip


def _pt_day(d: date) -> str:
    return f"{d.day} de {_MESES[d.month - 1]}"


def rule_text(p: HouseholdPolicy) -> str:
    """A regra da sala em linguagem simples (sem números inventados: só os da própria regra)."""
    if p.common_area_rule is CommonAreaRule.equal:
        return "a conta da sala é dividida por igual"
    if p.common_area_rule is CommonAreaRule.ask:
        return (
            f"pergunta-se «De quem é esta conta?» acima de {format_eur(p.ask_threshold_cents)}"
            f" (sem resposta em {p.ask_timeout_hours} h, fica por igual)"
        )
    return "a conta da sala é dividida por quem estava em casa"


def _rules_notification(
    *, proposal_id: UUID, step: str, household_id: UUID, recipient: UUID, title: str, body: str,
    severity: NotificationSeverity, correlation_id: UUID, now: datetime,
) -> Notification:  # fmt: skip
    return Notification(
        # Um aviso por proposta, passo (votar/aprovada/…) e pessoa: reentregas não duplicam.
        id=notification_id_for_ref(NotificationKind.info, uuid5(proposal_id, step), recipient),
        household_id=household_id,
        scope=NotificationScope.personal,
        recipient_resident_id=recipient,
        kind=NotificationKind.info,
        severity=severity,
        title=title,
        # Uma decisão da casa, não uma medição: não leva etiqueta SIMULADO/REAL.
        body=body,
        origin=Origin.real,
        ref=NotificationRef(type=RefType.rules_proposal, id=proposal_id),
        correlation_id=correlation_id,
        created_at=now,
    )


def compose_rules_vote(
    *, proposal_id: UUID, household_id: UUID, recipient: UUID, policy: HouseholdPolicy,
    effective_from: date, needed: int, eligible: int, correlation_id: UUID, now: datetime,
) -> Notification:  # fmt: skip
    """A cada morador (menos quem propôs): há uma proposta para votar na página da casa."""
    return _rules_notification(
        proposal_id=proposal_id, step="vote", household_id=household_id, recipient=recipient,
        title="Proposta de mudança da regra da sala",
        body=(
            f"Foi proposto que, a partir de {_pt_day(effective_from)}, {rule_text(policy)}. "
            f"Só muda se pelo menos {needed} de {eligible} moradores aprovarem. "
            "Vota na página da casa."
        ),
        severity=NotificationSeverity.info, correlation_id=correlation_id, now=now,
    )  # fmt: skip


def compose_rules_approved(
    *, proposal_id: UUID, household_id: UUID, recipient: UUID, policy: HouseholdPolicy,
    effective_from: date, correlation_id: UUID, now: datetime,
) -> Notification:  # fmt: skip
    """A toda a casa (moradores e senhorio): a mudança foi aprovada e já está agendada."""
    return _rules_notification(
        proposal_id=proposal_id, step="approved", household_id=household_id, recipient=recipient,
        title=f"A regra da sala muda a {_pt_day(effective_from)}",
        body=(
            f"A maioria dos moradores aprovou: a partir de {_pt_day(effective_from)}, "
            f"{rule_text(policy)}. O mês em curso e as faturas fechadas não mudam."
        ),
        severity=NotificationSeverity.info, correlation_id=correlation_id, now=now,
    )  # fmt: skip


def compose_rules_not_approved(
    *, proposal_id: UUID, household_id: UUID, recipient: UUID, expired: bool,
    correlation_id: UUID, now: datetime,
) -> Notification:  # fmt: skip
    """A quem propôs: não houve maioria (rejeitada ou caducou com o mês). Nada muda."""
    return _rules_notification(
        proposal_id=proposal_id, step="expired" if expired else "rejected",
        household_id=household_id, recipient=recipient,
        title="A tua proposta de regra não foi aprovada",
        body=(
            "O mês começou sem a maioria dos moradores a aprovar; a regra da sala fica igual."
            if expired
            else "A maioria dos moradores já não pode aprovar; a regra da sala fica igual."
        ),
        severity=NotificationSeverity.info, correlation_id=correlation_id, now=now,
    )  # fmt: skip
