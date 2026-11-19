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


SECURITY_NOTICE = (
    "SIMULADO: este painel é uma simulação. Armar ou desarmar só muda o painel simulado; "
    "nada é armado, desarmado nem executado na casa real, e não substitui um alarme certificado."
)
PANEL_RESULT = {
    "arm": "SIMULADO: o painel simulado ficou armado. Nenhum alarme real foi armado.",
    "disarm": "SIMULADO: o painel simulado ficou desarmado. Nenhum alarme real foi desarmado.",
}
ASSESSMENT_TEXT = {
    "consistent": "O painel simulado está armado e não parece estar ninguém em casa.",
    "suggest_arm": (
        "Parece não estar ninguém em casa e o painel simulado está desarmado. "
        "Podes propor armar (só simulado, com a tua confirmação)."
    ),
    "armed_with_people": (
        "O painel simulado está armado, mas há sinais de que alguém está em casa. "
        "É uma pergunta, não uma acusação: confirma se é isso que queres."
    ),
    "normal": "Há sinais de pessoas em casa e o painel simulado está desarmado.",
    "no_signal": (
        "Sem sinal fiável: a casa não é dada como vazia sem o sinal da presença, e um painel "
        "sem leitura não é dado como armado nem desarmado."
    ),
}
