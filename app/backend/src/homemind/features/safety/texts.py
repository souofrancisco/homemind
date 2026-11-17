"""Texto (pt-PT) dos alertas, para a app/notificações (P3). O contrato não tem campo de texto."""

from homemind.contracts.safety import SafetyAlert, SafetyAlertKind


def origin_label(alert: SafetyAlert) -> str:
    return "SIMULADO" if alert.provenance.simulated else "REAL"


def alert_text(alert: SafetyAlert) -> str:
    tag = f"[{origin_label(alert)}] "
    if alert.kind is SafetyAlertKind.smoke:
        return (
            tag + "Detetor de fumo em alarme. Siga o plano de emergência da casa e, se houver "
            "perigo, ligue 112. Este sistema não substitui detetores de fumo certificados "
            "nem sugere desligar equipamentos."
        )
    return (
        tag + "Janela aberta há mais de 5 minutos com o aquecedor ligado. Sugestão: desligar a "
        "tomada (precisa da sua confirmação). Atenção: a tomada pode alimentar mais do que o "
        "aquecedor (na demo, a tomada agregada corta todas as cargas ligadas a ela)."
    )
