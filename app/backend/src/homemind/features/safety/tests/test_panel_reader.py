"""Leitura só de leitura do alarme (SAFE-02 #115) com respostas MCP FALSAS. Nunca rede, MCP nem
hardware. A fixture REAL (2026-11-19) só prova que `alarmState=normal` é `unknown`; os valores
`armed`/`disarmed` são um FORMATO ASSUMIDO, por confirmar com uma resposta real."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from homemind.contracts.common import Origin
from homemind.contracts.safety import SecurityPanelStatus as S
from homemind.features.safety.panel_reader import (
    STALE_AFTER,
    SecurityPanelCache,
    panel_state,
    panel_status_from_devices,
)

HOUSE = UUID(int=7)
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
REAL = json.loads(
    (Path(__file__).parent / "fixtures" / "mcp_gateway_real_2026-11-19.json").read_text()
)


def gateway(value, **over):  # FORMATO ASSUMIDO, por confirmar com resposta real
    d = {
        "id": "g",
        "type": "gateway",
        "categories": ["security"],
        "capabilities": [{"type": "alarmState", "value": value}],
    }
    return {**d, **over}


def test_real_capture_is_unknown_never_inferred():
    # alarmState=normal é o estado de disparo, não o de armamento: não é «desarmado»
    assert panel_status_from_devices(REAL["devices"]) is S.unknown


@pytest.mark.parametrize(
    ("devices", "expected"),
    [
        ([gateway("armed")], S.armed),  # formato assumido
        ([gateway("disarmed")], S.disarmed),  # formato assumido
        ([gateway("armed"), gateway("armed")], S.armed),
        ([gateway("armed"), gateway("disarmed")], S.unknown),  # contradição
        ([gateway("armed"), gateway("normal")], S.unknown),  # um gateway sem leitura
        ([], S.unknown),  # dispositivo ausente
        ([{"type": "plug", "capabilities": []}], S.unknown),
        ([gateway("normal")], S.unknown),
        ([gateway("alarm")], S.unknown),
        ([gateway("ARMED")], S.unknown),  # sem normalização por inferência
        ([gateway("armed_home")], S.unknown),  # valor desconhecido
        ([gateway("")], S.unknown),
        ([gateway(None)], S.unknown),
        ([gateway(True)], S.unknown),
        ([gateway(1)], S.unknown),
        ([gateway(["armed"])], S.unknown),
        ([gateway({"x": "armed"})], S.unknown),
        ([gateway("armed", capabilities=[])], S.unknown),  # capability não suportada
        ([gateway("armed", capabilities=None)], S.unknown),
        ([gateway("armed", capabilities="armed")], S.unknown),
        ([gateway("armed", capabilities=[{"type": "alarmState"}])], S.unknown),
        (
            [gateway("armed", capabilities=[{"type": "alarmState", "value": "armed"}] * 2)],
            S.unknown,
        ),
        ([gateway("armed", categories=[])], S.unknown),  # não é dispositivo de segurança
        ([gateway("armed", categories="security")], S.unknown),
        ([gateway("armed", type=["gateway"])], S.unknown),
        (["gateway", None, 3, gateway("armed")], S.armed),  # lixo ao lado é ignorado
        ([[gateway("armed")]], S.unknown),
        ({"devices": [gateway("armed")]}, S.unknown),  # resposta malformada (não é lista)
        ("armed", S.unknown),
        (None, S.unknown),
    ],
)
def test_parser_fails_safe(devices, expected):
    assert panel_status_from_devices(devices) is expected


def test_state_is_real_and_labeled():
    armed = panel_state(HOUSE, S.armed, NOW)
    assert armed.provenance.origin is Origin.real and not armed.provenance.simulated
    assert armed.provenance.kind.value == "measured"
    assert panel_state(HOUSE, S.unknown, NOW).provenance.kind.value == "estimated"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def test_cache_reads_and_keeps_since_while_state_is_unchanged():
    clock = Clock()
    cache = SecurityPanelCache(HOUSE, clock)
    assert cache.read(HOUSE, NOW).status is S.unknown  # sem leitura
    cache.ingest([gateway("armed")])
    first = cache.read(HOUSE, NOW)
    assert first.status is S.armed and first.since == NOW and first.provenance.origin is Origin.real
    clock.now = NOW + timedelta(seconds=30)
    cache.ingest([gateway("armed")])
    assert cache.read(HOUSE, clock.now).since == NOW  # não mudou
    clock.now = NOW + timedelta(seconds=40)
    cache.ingest([gateway("disarmed")])
    assert cache.read(HOUSE, clock.now).since == clock.now


def test_cache_is_house_scoped_stale_and_cleared_on_failure():
    clock = Clock()
    cache = SecurityPanelCache(HOUSE, clock)
    cache.ingest([gateway("armed")])
    assert cache.read(UUID(int=8), NOW) is None  # outra casa: nunca devolve esta
    assert cache.read(HOUSE, NOW + STALE_AFTER + timedelta(seconds=1)).status is S.unknown
    cache.unavailable()  # erro/timeout do MCP
    assert cache.read(HOUSE, NOW).status is S.unknown
    cache.ingest("lixo")  # resposta malformada nunca deixa o estado anterior
    assert cache.read(HOUSE, NOW).status is S.unknown
