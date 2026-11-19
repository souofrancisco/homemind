"""Estimativa da lâmpada (9 W × tempo × brilho, #248 F3). Puro, relógio simulado, sem MCP."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from homemind.contracts.common import Origin, ValueKind, stable_id
from homemind.contracts.domain_events import EnergyConsumptionClosed, EnergyConsumptionDetected
from homemind.contracts.energy import ConsumptionStatus, LocationKind
from homemind.features.energy.lamp import LAMP_WATTS, LampEstimator

T0 = datetime(2026, 11, 18, 20, tzinfo=UTC)
HOUSE = stable_id("house", "lamp")
DEVICE = stable_id("device", "lamp")
ROOM = stable_id("room", "sala")


@pytest.fixture
def lamp():
    events: list = []
    registered: list = []

    def register() -> UUID:
        registered.append(1)
        return DEVICE

    est = LampEstimator(
        HOUSE,
        register=register,
        locate=lambda _device: (LocationKind.common, ROOM),
        publish=events.append,
    )
    est.events, est.registered = events, registered
    return est


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_constante_nomeada():
    assert LAMP_WATTS == 9


def test_sessao_on_off_9w_vezes_tempo_vezes_brilho(lamp):
    lamp.observe(True, 100, at(0), Origin.simulated)
    lamp.observe(True, 100, at(30), Origin.simulated)
    lamp.observe(False, None, at(60), Origin.simulated)
    detected, closed = lamp.events
    assert isinstance(detected, EnergyConsumptionDetected)
    assert detected.data.status is ConsumptionStatus.ongoing and detected.data.energy_wh == 0
    assert isinstance(closed, EnergyConsumptionClosed)
    c = closed.data
    assert c.energy_wh == 9  # 9 W × 1 h × 100 %
    assert (c.started_at, c.ended_at) == (at(0), at(60))
    assert c.provenance.origin is Origin.simulated and c.provenance.kind is ValueKind.estimated
    assert (c.device_id, c.location, c.room_id) == (DEVICE, LocationKind.common, ROOM)
    assert c.match.appliance_id is None and c.cost_estimate is None
    assert closed.correlation_id == detected.correlation_id == c.id


def test_brilho_a_meio_conta_por_troços(lamp):
    lamp.observe(True, 100, at(0), Origin.real)
    lamp.observe(True, 50, at(60), Origin.real)  # 1.ª hora a 100 %: 9 Wh
    lamp.observe(False, None, at(180), Origin.real)  # 2 h a 50 %: 9 Wh
    assert lamp.events[-1].data.energy_wh == 18
    assert lamp.events[-1].data.provenance.origin is Origin.real
    assert lamp.events[-1].data.peak_w == 9.0


def test_indisponivel_fecha_no_ultimo_instante_observado(lamp):
    lamp.observe(True, 100, at(0), Origin.simulated)
    lamp.observe(True, 100, at(60), Origin.simulated)
    lamp.observe(None, None, at(600), Origin.simulated)  # 9 h sem a ver: não se inventa tempo
    closed = lamp.events[-1].data
    assert closed.ended_at == at(60) and closed.energy_wh == 9
    assert lamp.fechadas_sem_leitura == [closed.id]
    lamp.observe(None, None, at(700), Origin.simulated)
    assert len(lamp.events) == 2  # nada a fechar


def test_desligada_nunca_abre_sessao_nem_regista(lamp):
    lamp.observe(False, None, at(0), Origin.simulated)
    lamp.observe(None, None, at(1), Origin.simulated)
    assert lamp.events == [] and lamp.registered == []


def test_instantes_antigos_ignorados_e_ids_estaveis(lamp):
    def run(est):
        est.observe(True, 100, at(10), Origin.simulated)
        est.observe(True, 20, at(5), Origin.simulated)  # atrasada: ignorada
        est.observe(False, None, at(70), Origin.simulated)

    run(lamp)
    assert lamp.events[-1].data.energy_wh == 9
    again: list = []
    run(
        LampEstimator(
            HOUSE,
            register=lambda: DEVICE,
            locate=lambda _d: (LocationKind.common, ROOM),
            publish=again.append,
        )
    )
    assert [e.id for e in again] == [e.id for e in lamp.events]  # reentrega idempotente (D-19)
