"""Pedido em português → proposta de comando (ou recusa). Determinístico e puro: sem LLM.

Só trata de lâmpada (ligar, desligar, brilho 1–100, cor da paleta de `contracts.home.CORES`) e
de tomada (só desligar: o agente nunca liga uma tomada). Tudo o resto é recusado com um código
(`forbidden_kind`, `plug_turn_on_not_allowed`, `ambiguous_device`, `no_device`, `unsupported`) e
nunca se adivinha: na dúvida recusa-se. Esta camada não executa nada nem toca em dispositivos.
"""

import re
from dataclasses import dataclass
from typing import Final

from homemind.contracts.agent import DeviceCapability, DeviceCommand, RgbColor
from homemind.contracts.devices import DeviceKind
from homemind.contracts.home import CORES
from homemind.features.agent.devices import ActuatorDevice
from homemind.features.agent.guardrails import plain

MAX_RATIONALE = 300

_OFF = re.compile(r"\b(desliga\w*|apaga\w*)\b")
_ON = re.compile(r"\b(liga|ligar|ligues?|ligam|acende\w*)\b")
_BULB = re.compile(r"\b(luz|luzes|lampada\w*|candeeiro\w*|iluminacao)\b")
_PLUG = re.compile(r"\b(tomada\w*|ficha|aquecedor\w*|extensao|extensoes|regua)\b")
_FORBIDDEN = re.compile(
    r"\b(alarme\w*|cenario\w*|seguranca|sirene\w*|fechadura\w*|trinco|timer\w*|temporizador\w*)\b"
)
# Agendar, condicionar ou repetir: a proposta é sempre «agora», por isso recusa-se.
_SCHEDULE = re.compile(
    r"\b\d{1,2}\s*h\b|\b\d{1,2}\s*horas?\b|\b\d{1,2}:\d{2}\b|\bas\s+\d{1,2}\b"
    r"|\b\d+\s*(?:min\w*|seg\w*)\b|\bdaqui a\b|\bdentro de\b|\bdepois\b|\bamanha\b"
    r"|\bmais tarde\b|\bquando\b|\bsempre que\b|\btodos os dias\b|\bagenda\w*\b"
)
_BRIGHTNESS_WORD = re.compile(r"\b(brilho|intensidade)\b")
_PERCENT = re.compile(r"\b(\d{1,4})\s*(?:%|por cento)")
_NUMBER = re.compile(r"\b(\d{1,4})\b")

# Nome da paleta ← formas escritas (sem acentos). As mais longas primeiro.
_COLOR_WORDS: Final[tuple[tuple[str, str], ...]] = tuple(
    sorted(
        [(name.replace("_", " "), name) for name in CORES]
        + [
            ("branca quente", "branco_quente"),
            ("branca fria", "branco_frio"),
            ("branca", "branco"),
            ("vermelha", "vermelho"),
            ("amarela", "amarelo"),
            ("roxa", "roxo"),
        ],
        key=lambda item: -len(item[0]),
    )
)
_STOP = {"luz", "luzes", "lampada", "tomada", "da", "de", "do", "das", "dos", "a", "o", "e"}


@dataclass(frozen=True)
class ActionIntent:
    device: ActuatorDevice
    command: DeviceCommand
    rationale: str


@dataclass(frozen=True)
class Refusal:
    # forbidden_kind | plug_turn_on_not_allowed | ambiguous_device | no_device | unsupported
    code: str
    text: str


def _refuse(code: str, text: str) -> Refusal:
    return Refusal(code, text)


_HELP = (
    "Posso propor desligar a tomada, ou ligar, desligar, mudar o brilho (1 a 100) ou a cor da "
    "lâmpada. Nada é executado sem a tua confirmação."
)


def _color(text: str) -> str | None:
    for word, name in _COLOR_WORDS:
        if re.search(rf"\b{word}\b", text):
            return name
    return None


def _brightness(text: str) -> tuple[bool, int | None]:
    """(houve pedido de brilho, valor). Valor fora de 1–100 ou em falta fica `None`."""
    percent = _PERCENT.search(text)
    word = _BRIGHTNESS_WORD.search(text)
    if not word and not percent:
        return False, None
    found = percent or _NUMBER.search(text)
    if not found:
        return True, None
    value = int(found.group(1))
    return True, value if 1 <= value <= 100 else None


def _pick(candidates: list[ActuatorDevice], text: str) -> ActuatorDevice | None:
    """Um dispositivo único do tipo pedido; com vários, só se o texto distinguir um (o nome)."""
    if len(candidates) == 1:
        return candidates[0]
    words = set(re.findall(r"\w+", text))

    def score(d: ActuatorDevice) -> int:
        return sum(t not in _STOP and len(t) > 2 and t in words for t in plain(d.name).split())

    scores = sorted(((score(d), i) for i, d in enumerate(candidates)), reverse=True)
    best = scores[0]
    return candidates[best[1]] if best[0] > 0 and scores[1][0] < best[0] else None


def _rationale(verb: str, device: ActuatorDevice) -> str:
    """Nomeia o dispositivo; avisa da extensão agregada; diz SIMULADO. Cabe em 300 caracteres."""
    name = device.name if len(device.name) <= 80 else device.name[:79] + "…"
    out = f"{verb} «{name}»."
    # SIMULADO fica sempre dentro do limite: é a etiqueta que nunca se pode perder.
    tail = " SIMULADO: nada real é tocado." if device.simulated else ""
    warning = (
        "Alimenta vários aparelhos: desligá-la corta tudo o que lá estiver ligado (por exemplo, o "
        "aquecedor)."
    )
    if device.aggregate and len(out) + 1 + len(warning) + len(tail) <= MAX_RATIONALE:
        out += " " + warning
    return out + tail


def parse_action(text: str, devices: list[ActuatorDevice]) -> ActionIntent | Refusal:
    t = plain(text)
    if _FORBIDDEN.search(t):
        return _refuse(
            "forbidden_kind",
            "Não proponho nada sobre alarmes, segurança, cenários ou temporizadores. " + _HELP,
        )
    if _SCHEDULE.search(t):
        return _refuse(
            "unsupported",
            "Ainda não agendo nem condiciono ações: só proponho uma ação para agora, que "
            "confirmas tu. " + _HELP,
        )

    on, off = _ON.search(t) is not None, _OFF.search(t) is not None
    color = _color(t)
    wants_brightness, brightness = _brightness(t)
    caps = [
        c
        for c, wanted in (
            (DeviceCapability.power, on or off),
            (DeviceCapability.color_rgb, color is not None),
            (DeviceCapability.brightness, wants_brightness),
        )
        if wanted
    ]
    if on and off:
        return _refuse("unsupported", "O pedido é contraditório (ligar e desligar). " + _HELP)
    if len(caps) != 1:
        return _refuse(
            "unsupported",
            "Só proponho uma coisa de cada vez (ligar/desligar, brilho ou cor). " + _HELP,
        )
    cap = caps[0]
    if cap is DeviceCapability.brightness and brightness is None:
        return _refuse("unsupported", "O brilho tem de ser um valor entre 1 e 100. " + _HELP)

    bulb, plug = _BULB.search(t) is not None, _PLUG.search(t) is not None
    if bulb and plug:
        return _refuse("ambiguous_device", "Pediste a luz e a tomada. Diz-me só uma delas.")
    kind = DeviceKind.bulb if bulb else DeviceKind.plug if plug else None
    if kind is None and cap is not DeviceCapability.power:
        kind = DeviceKind.bulb  # cor e brilho só existem na lâmpada
    if kind is None:
        return _refuse("ambiguous_device", "Qual o dispositivo: a luz ou a tomada?")
    if kind is DeviceKind.plug and cap is not DeviceCapability.power:
        return _refuse("unsupported", "A tomada só se liga e desliga; não tem cor nem brilho.")
    if kind is DeviceKind.plug and on:
        return _refuse(
            "plug_turn_on_not_allowed",
            "Não ligo tomadas: o assistente só propõe desligar. Liga-a tu, se for seguro.",
        )

    candidates = [d for d in devices if d.kind is kind]
    if not candidates:
        what = "lâmpada" if kind is DeviceKind.bulb else "tomada"
        return _refuse(
            "no_device", f"Não encontro nenhuma {what} que eu possa comandar nesta casa."
        )
    device = _pick(candidates, t)
    if device is None:
        return _refuse("ambiguous_device", "Há vários dispositivos assim. Diz-me qual (pelo nome).")

    if cap is DeviceCapability.power:
        command = DeviceCommand(target_device_id=device.id, capability=cap, power=on)
        verb = "Ligar" if on else "Desligar"
        return ActionIntent(device, command, _rationale(verb, device))
    if cap is DeviceCapability.brightness:
        assert brightness is not None
        command = DeviceCommand(target_device_id=device.id, capability=cap, brightness=brightness)
        return ActionIntent(
            device, command, _rationale(f"Pôr o brilho a {brightness} % em", device)
        )
    assert color is not None
    r, g, b = CORES[color]
    command = DeviceCommand(
        target_device_id=device.id, capability=cap, color_rgb=RgbColor(r=r, g=g, b=b)
    )
    return ActionIntent(
        device, command, _rationale(f"Mudar a cor para {color.replace('_', ' ')} em", device)
    )
