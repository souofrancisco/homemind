"""Parser de pedidos de ação (PT, determinístico): propostas e recusas. Sem LLM, sem rede."""

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.agent import DeviceCapability
from homemind.contracts.devices import DeviceKind
from homemind.features.agent.devices import ActuatorDevice, DemoDevices
from homemind.features.agent.intents import MAX_RATIONALE, ActionIntent, Refusal, parse_action

DEVICES = DemoDevices().actuators(fx.HOUSEHOLD)
CAP = DeviceCapability


def intent(text, devices=DEVICES) -> ActionIntent:
    r = parse_action(text, devices)
    assert isinstance(r, ActionIntent), r
    return r


def refusal(text, devices=DEVICES) -> str:
    r = parse_action(text, devices)
    assert isinstance(r, Refusal), r
    return r.code


@pytest.mark.parametrize(
    "text",
    ["Desliga a luz", "apaga a luz da sala", "podes desligar a lâmpada?", "desliga o candeeiro"],
)
def test_desligar_a_lampada(text):
    r = intent(text)
    assert r.device.kind is DeviceKind.bulb and r.command.capability is CAP.power
    assert r.command.power is False


@pytest.mark.parametrize("text", ["liga a luz", "acende a luz", "Acende a lâmpada, por favor"])
def test_ligar_a_lampada(text):
    r = intent(text)
    assert r.device.kind is DeviceKind.bulb and r.command.power is True


@pytest.mark.parametrize(
    "text",
    ["desliga a tomada", "Desliga o aquecedor da sala", "apaga a extensão", "desliga a ficha"],
)
def test_desligar_a_tomada_avisa_que_e_a_extensao(text):
    r = intent(text)
    assert r.device.kind is DeviceKind.plug and r.command.power is False
    assert r.device.name in r.rationale and "vários aparelhos" in r.rationale


@pytest.mark.parametrize(
    ("text", "rgb"),
    [
        ("põe a luz azul", (0, 0, 255)),
        ("muda a cor da luz para vermelho", (255, 0, 0)),
        ("muda a cor para branco quente", (255, 170, 90)),
        ("pon a luz branca fria".replace("pon", "põe"), (200, 220, 255)),
    ],
)
def test_cor_da_paleta(text, rgb):
    r = intent(text)
    assert r.command.capability is CAP.color_rgb
    c = r.command.color_rgb
    assert (c.r, c.g, c.b) == rgb


@pytest.mark.parametrize(
    ("text", "value"),
    [("põe o brilho a 50", 50), ("brilho da luz a 100%", 100), ("coloca a luz a 1 por cento", 1)],
)
def test_brilho(text, value):
    r = intent(text)
    assert r.command.capability is CAP.brightness and r.command.brightness == value


def test_racional_nomeia_o_dispositivo_e_diz_simulado():
    lamp = intent("desliga a luz")
    assert "Lâmpada da sala" in lamp.rationale and "SIMULADO" in lamp.rationale
    assert len(lamp.rationale) <= MAX_RATIONALE
    plug = intent("desliga a tomada")
    assert "Tomada da extensão" in plug.rationale and "SIMULADO" in plug.rationale
    assert len(plug.rationale) <= MAX_RATIONALE


def test_racional_de_dispositivo_real_nao_diz_simulado():
    real = ActuatorDevice(fx.LAMP, "Candeeiro " + "x" * 110, DeviceKind.bulb, simulated=False)
    r = intent("desliga a luz", [real])
    assert "SIMULADO" not in r.rationale and len(r.rationale) <= MAX_RATIONALE


def test_racional_longo_simulado_mantem_a_etiqueta():
    long = ActuatorDevice(fx.METER, "T" * 120, DeviceKind.plug, simulated=True, aggregate=True)
    r = intent("desliga a tomada", [long])
    assert r.rationale.endswith("SIMULADO: nada real é tocado.")
    assert len(r.rationale) <= MAX_RATIONALE


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("arma o alarme", "forbidden_kind"),
        ("ativa o cenário de noite", "forbidden_kind"),
        ("desliga a segurança", "forbidden_kind"),
        ("desliga a sirene", "forbidden_kind"),
        ("liga a tomada", "plug_turn_on_not_allowed"),
        ("liga o aquecedor", "plug_turn_on_not_allowed"),
        ("acende a tomada da extensão", "plug_turn_on_not_allowed"),
        ("desliga a luz e a tomada", "ambiguous_device"),
        ("desliga", "ambiguous_device"),
        ("desliga já sem confirmar", "ambiguous_device"),
        ("desliga a luz às 23h", "unsupported"),
        ("desliga a tomada daqui a 10 minutos", "unsupported"),
        ("põe o brilho a 120", "unsupported"),
        ("põe o brilho a 0", "unsupported"),
        ("baixa o brilho", "unsupported"),
        ("liga e desliga a luz", "unsupported"),
        ("acende a luz azul", "unsupported"),  # uma coisa de cada vez
        ("põe a tomada azul", "unsupported"),
        ("qual a cor do meu recibo", "unsupported"),
    ],
)
def test_recusas(text, code):
    assert refusal(text) == code


def test_sem_dispositivos_nao_ha_proposta():
    assert refusal("desliga a luz", []) == "no_device"
    assert refusal("desliga a tomada", []) == "no_device"


def test_so_ha_lampada_ou_so_ha_tomada():
    bulbs = [d for d in DEVICES if d.kind is DeviceKind.bulb]
    assert refusal("desliga a tomada", bulbs) == "no_device"
    assert intent("desliga a luz", bulbs).device.kind is DeviceKind.bulb


def test_varios_dispositivos_do_mesmo_tipo_exigem_o_nome():
    a = ActuatorDevice(fx.LAMP, "Candeeiro da sala", DeviceKind.bulb, True)
    b = ActuatorDevice(fx.METER, "Candeeiro do quarto", DeviceKind.bulb, True)
    assert refusal("desliga a luz", [a, b]) == "ambiguous_device"
    assert intent("desliga o candeeiro da sala", [a, b]).device == a
    assert intent("desliga o candeeiro do quarto", [a, b]).device == b


def test_o_parser_nao_executa_nada():
    # Puro: devolve dados; o estado do diretório não muda e não há I/O.
    before = list(DEVICES)
    intent("desliga a luz")
    assert DEVICES == before
