"""SAFE-01/03: regras puras, relógio = ts dos eventos. Tudo SIMULADO."""

from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.safety import SafetyAlertKind, SafetyAlertStatus
from homemind.contracts.sensors import ContactState as C
from homemind.contracts.sensors import SensorKind, SensorStatus
from homemind.features.safety import simulation as sim
from homemind.features.safety.engine import SafetyEngine
from homemind.features.safety.texts import alert_text

T0 = fx.T0


def at(m: float):
    return T0 + timedelta(minutes=m)


def engine(**kw):
    return SafetyEngine(lambda a: a == fx.HEATER, **kw)


def feed(e, *events):
    out = []
    for ev in events:
        out += e.on_event(ev)
    return out


def test_window_open_5min_with_heater_raises_one_alert_with_power_off_proposal():
    e = engine()
    out = feed(e, sim.heater_on(T0), sim.contact(T0, C.open), sim.contact(at(4.9), C.open))
    assert out == []
    out = feed(e, sim.contact(at(5), C.open))
    assert len(out) == 1
    a = out[0].data
    assert a.kind is SafetyAlertKind.window_open_heating and a.status is SafetyAlertStatus.active
    assert a.suggested_command.power is False and a.suggested_command.target_device_id == fx.METER
    assert a.consumption_event_id == fx.CONSUMPTION and a.room_id == fx.ROOM_SALA
    assert a.provenance.simulated
    assert "corta todas as cargas" in alert_text(a) and "SIMULADO" in alert_text(a)


def test_repeated_readings_do_not_duplicate():
    e = engine()
    out = feed(e, sim.heater_on(T0), *[sim.contact(at(m), C.open) for m in range(0, 30)])
    assert len(out) == 1


def test_window_closed_before_5min_never_alerts_and_restarts_episode():
    e = engine()
    out = feed(
        e, sim.heater_on(T0), sim.contact(T0, C.open), sim.contact(at(4), C.closed),
        sim.contact(at(5), C.open), sim.contact(at(9), C.open),
    )  # fmt: skip
    assert out == []
    assert len(feed(e, sim.contact(at(10), C.open))) == 1  # 5 min desde a reabertura


def test_alert_resolves_when_window_closes_and_reopens_as_new_episode():
    e = engine()
    first = feed(e, sim.heater_on(T0), sim.contact(T0, C.open), sim.contact(at(5), C.open))
    res = feed(e, sim.contact(at(6), C.closed))
    assert len(res) == 1 and res[0].data.id == first[0].data.id
    assert res[0].data.status is SafetyAlertStatus.resolved and res[0].data.resolved_at == at(6)
    assert feed(e, sim.contact(at(7), C.open), sim.contact(at(11), C.open)) == []
    again = feed(e, sim.contact(at(12), C.open))
    assert len(again) == 1 and again[0].data.id != first[0].data.id


def test_heater_turning_off_resolves_and_it_turning_on_again_reopens():
    e = engine()
    first = feed(e, sim.heater_on(T0), sim.contact(T0, C.open), sim.contact(at(5), C.open))
    res = feed(e, sim.heater_off(at(6)))
    assert [r.data.status for r in res] == [SafetyAlertStatus.resolved]
    assert res[0].data.id == first[0].data.id
    assert feed(e, sim.contact(at(7), C.open)) == []  # janela aberta mas sem aquecedor
    again = feed(e, sim.heater_on(at(8)))  # janela já aberta há > 5 min: novo episódio
    assert len(again) == 1 and again[0].data.id != first[0].data.id


def test_heater_turning_on_after_window_open_5min_triggers_on_consumption():
    e = engine()
    assert feed(e, sim.contact(T0, C.open), sim.contact(at(6), C.open)) == []
    assert len(feed(e, sim.heater_on(at(7)))) == 1


@pytest.mark.parametrize("status", [SensorStatus.unknown, SensorStatus.stale])
def test_unusable_sensor_never_fires_nor_resolves(status):
    e = engine()
    assert feed(e, sim.heater_on(T0), sim.contact(T0, C.open),
                sim.contact(at(3), None, status=status), sim.contact(at(8), None, status=status)) == []  # fmt: skip # noqa: E501
    assert e.coverage(fx.HOUSEHOLD)[SensorKind.contact] == status.value
    # um alerta ativo não é fechado por uma leitura inutilizável
    e2 = engine()
    feed(e2, sim.heater_on(T0), sim.contact(T0, C.open), sim.contact(at(5), C.open))
    assert feed(e2, sim.contact(at(6), None, status=status)) == []


def test_not_heating_appliance_or_other_room_or_no_room_does_not_fire():
    e = SafetyEngine(lambda a: False)
    assert feed(e, sim.heater_on(T0), sim.contact(T0, C.open), sim.contact(at(9), C.open)) == []
    e = engine()
    assert feed(e, sim.heater_on(T0), sim.contact(T0, C.open, room=fx.ROOM_ANA, device=fx.LAMP),
                sim.contact(at(9), C.open, room=fx.ROOM_ANA, device=fx.LAMP)) == []  # fmt: skip
    e = engine()
    assert feed(e, sim.heater_on(T0), sim.contact(T0, C.open, room=None),
                sim.contact(at(9), C.open, room=None)) == []  # fmt: skip


def test_absent_sensor_is_reported_and_no_alert():
    e = engine()
    assert feed(e, sim.heater_on(T0)) == []
    assert e.coverage(fx.HOUSEHOLD) == {SensorKind.contact: "absent", SensorKind.smoke: "absent"}


def test_smoke_critical_dedup_no_cut_suggestion_and_resolution():
    e = engine()
    out = feed(e, sim.smoke(T0, False), sim.smoke(at(1), True), sim.smoke(at(1.1), True))
    assert len(out) == 1
    a = out[0].data
    assert a.kind is SafetyAlertKind.smoke and a.severity.value == "critical"
    assert a.suggested_command is None and a.provenance.simulated
    assert a.notify_landlord is False  # sem política que o autorize
    assert "não substitui detetores de fumo certificados" in alert_text(a)
    res = feed(e, sim.smoke(at(3), False))
    assert res[0].data.status is SafetyAlertStatus.resolved and res[0].data.id == a.id
    assert len(feed(e, sim.smoke(at(4), True))) == 1  # novo episódio


def test_smoke_notify_landlord_only_when_enabled():
    e = engine(notify_landlord=True)
    assert feed(e, sim.smoke(T0, True))[0].data.notify_landlord is True


@pytest.mark.parametrize("status", [SensorStatus.unknown, SensorStatus.stale])
def test_smoke_unusable_gives_no_false_alert_and_does_not_clear(status):
    e = engine()
    assert feed(e, sim.smoke(T0, None, status=status)) == []
    assert e.coverage(fx.HOUSEHOLD)[SensorKind.smoke] == status.value
    feed(e, sim.smoke(at(1), True))
    assert feed(e, sim.smoke(at(2), None, status=status)) == []
