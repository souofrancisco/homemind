"""Picos nas zonas comuns (ALERT-03): > 1,5 kW durante > 30 min, um aviso por incidente.

Casa demo SIMULADA; leituras de 30 em 30 s a partir de `fx.T0`."""

import time
from datetime import timedelta

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import (
    ApplianceCandidate,
    ApplianceMatch,
    ConsumptionStatus,
    ReadingStatus,
)
from homemind.features.billing import peaks

SALA_PLUG = stable_id("device", "tomada-sala")
QUARTO_PLUG = stable_id("device", "tomada-quarto-ana")
SALA_METER = stable_id("device", "contador-geral")
LOOSE_PLUG = stable_id("device", "tomada-sem-divisao")
UNKNOWN_PLUG = stable_id("device", "tomada-nao-registada")
COMMON_HEATER = stable_id("appliance", "aquecedor-da-sala")
STEP = timedelta(seconds=30)
T0_US = fx.T0.isoformat(timespec="microseconds")  # o catálogo exige microssegundos


def _devices(app):
    def work(conn):
        for did, room, role in (
            (SALA_PLUG, fx.ROOM_SALA, "none"),
            (QUARTO_PLUG, fx.ROOM_ANA, "room_meter"),
            (SALA_METER, fx.ROOM_SALA, "main_meter"),
            (LOOSE_PLUG, None, "none"),
        ):
            conn.execute(
                "INSERT INTO device (id, household_id, room_id, name, kind, role, source)"
                " VALUES (?,?,?,?,'plug',?,'fake')",
                (str(did), str(fx.HOUSEHOLD), room and str(room), f"tomada {did}", role),
            )

    app.state.db.run_sync(work)


def _appliance(app, appliance_id, name, scope, owner=None):
    def work(conn):
        conn.execute(
            "INSERT INTO appliance (id, household_id, name, category, registered_by_resident_id,"
            " created_at) VALUES (?,?,?,'heating',?,?)",
            (str(appliance_id), str(fx.HOUSEHOLD), name, str(fx.ANA), T0_US),
        )
        conn.execute(
            "INSERT INTO appliance_state (id, appliance_id, household_id, scope,"
            " owner_resident_id, home_room_id, valid_from, changed_by_resident_id)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                str(stable_id("appliance_state", str(appliance_id))),
                str(appliance_id),
                str(fx.HOUSEHOLD),
                scope,
                owner and str(owner),
                str(fx.ROOM_SALA),
                T0_US,
                str(fx.ANA),
            ),
        )

    app.state.db.run_sync(work)


def _ongoing(app, appliance_id, confidence, device=SALA_PLUG, name="c"):
    """Consumo a decorrer na tomada, como o billing o guarda (vindo de energy)."""
    c = replace(
        fx.consumption(),
        id=stable_id("consumption", name),
        device_id=device,
        match=ApplianceMatch(
            appliance_id=appliance_id,
            confidence=confidence,
            candidates=[ApplianceCandidate(appliance_id=appliance_id, confidence=confidence)],
        ),
        appliance_owner_resident_id=None,
    )
    assert c.status is ConsumptionStatus.ongoing
    app.state.db.run_sync(
        lambda conn: conn.execute(
            "INSERT INTO billing_consumption (id, household_id, status, started_at, energy_wh,"
            " json, updated_at) VALUES (?,?,'ongoing',?,?,?,?)",
            (
                str(c.id),
                str(fx.HOUSEHOLD),
                c.started_at.isoformat(),
                c.energy_wh,
                c.model_dump_json(),
                fx.T0.isoformat(),
            ),
        )
    )


def _reading(device, watts, at):
    return replace(
        fx.reading(watts, at),
        id=stable_id("reading", str(device), at.isoformat()),
        device_id=device,
    )


def _feed(app, device, watts, start, minutes):
    """Leituras de 30 em 30 s durante `minutes` (inclui as duas pontas); devolve os eventos."""
    out = []
    for i in range(int(minutes * 2) + 1):
        r = _reading(device, watts, start + i * STEP)
        out += app.state.db.run_sync(lambda c, r=r: peaks.observe(c, fx.HOUSEHOLD, r))
    return out


def test_aquecedor_na_sala_avisa_uma_vez_logo_depois_dos_30_min(app):
    _devices(app)
    assert _feed(app, SALA_PLUG, 2000, fx.T0, 30) == []  # 30 min certos ainda não é «> 30 min»
    [ev] = _feed(app, SALA_PLUG, 2040, fx.T0 + timedelta(minutes=30, seconds=30), 0)
    assert isinstance(ev, de.AlertsAlertRaised)
    assert ev.ts == fx.T0 + timedelta(minutes=30, seconds=30)
    d = ev.data
    assert (d.kind, d.severity.value) == (de.AlertKind.peak, "warning")
    assert (d.device_id, d.room_id, d.power_w, d.since) == (SALA_PLUG, fx.ROOM_SALA, 2040, fx.T0)
    assert d.appliance_id is None and ev.provenance.simulated
    # continua ligado mais 2 h: nenhum aviso repetido
    assert _feed(app, SALA_PLUG, 2000, fx.T0 + timedelta(minutes=31), 120) == []


def test_reentrega_da_mesma_leitura_nao_duplica(app):
    _devices(app)
    _feed(app, SALA_PLUG, 2000, fx.T0, 30)
    r = _reading(SALA_PLUG, 2000, fx.T0 + timedelta(minutes=31))
    first = app.state.db.run_sync(lambda c: peaks.observe(c, fx.HOUSEHOLD, r))
    again = app.state.db.run_sync(lambda c: peaks.observe(c, fx.HOUSEHOLD, r))
    assert len(first) == 1 and again == []


def test_abaixo_ou_igual_ao_limite_ou_curto_nao_avisa(app):
    _devices(app)
    assert _feed(app, SALA_PLUG, 1500, fx.T0, 90) == []  # 1,5 kW certos não é «acima»
    start = fx.T0 + timedelta(hours=2)
    assert _feed(app, SALA_PLUG, 2500, start, 25) == []  # chaleira/forno: pico curto
    assert _feed(app, SALA_PLUG, 100, start + timedelta(minutes=26), 1) == []
    assert _feed(app, SALA_PLUG, 2500, start + timedelta(minutes=28), 25) == []  # recomeça


def test_oscila_no_mesmo_incidente_sem_spam_e_rearma_depois(app):
    _devices(app)
    assert len(_feed(app, SALA_PLUG, 2000, fx.T0, 31)) == 1
    t = fx.T0 + timedelta(minutes=32)
    _feed(app, SALA_PLUG, 800, t, 10)  # termóstato desliga 10 min
    assert _feed(app, SALA_PLUG, 2000, t + timedelta(minutes=11), 40) == []  # mesmo incidente
    t += timedelta(minutes=52)
    _feed(app, SALA_PLUG, 50, t, 45)  # desligado 45 min: novo incidente pode avisar
    [ev] = _feed(app, SALA_PLUG, 2000, t + timedelta(minutes=46), 31)
    assert ev.data.since == t + timedelta(minutes=46)


def test_lacuna_longa_recomeca_a_contagem_e_leituras_sem_valor_nao_contam(app):
    _devices(app)
    _feed(app, SALA_PLUG, 2000, fx.T0, 20)
    # 15 min sem leituras: não se afirma que esteve acima o tempo todo
    assert _feed(app, SALA_PLUG, 2000, fx.T0 + timedelta(minutes=35), 25) == []
    missing = replace(
        _reading(SALA_PLUG, 2000, fx.T0 + timedelta(minutes=61)),
        status=ReadingStatus.missing,
        power_w=None,
        raw_value=None,
    )
    assert app.state.db.run_sync(lambda c: peaks.observe(c, fx.HOUSEHOLD, missing)) == []
    [ev] = _feed(app, SALA_PLUG, 2000, fx.T0 + timedelta(minutes=61), 5)
    assert ev.data.since == fx.T0 + timedelta(minutes=35)


def test_quarto_e_contador_geral_nunca_avisam(app):
    _devices(app)
    assert _feed(app, QUARTO_PLUG, 2000, fx.T0, 60) == []
    assert _feed(app, SALA_METER, 3000, fx.T0, 60) == []


def test_sem_localizacao_segura_e_pico_por_identificar(app):
    _devices(app)
    _ongoing(app, COMMON_HEATER, 0.95, device=LOOSE_PLUG)
    for device in (LOOSE_PLUG, UNKNOWN_PLUG):
        [ev] = _feed(app, device, 2000, fx.T0, 31)
        assert ev.data.room_id is None and ev.data.appliance_id is None


def test_aparelho_so_com_confianca_e_se_for_comum(app):
    _devices(app)
    _appliance(app, COMMON_HEATER, "Aquecedor da sala", "common")
    _ongoing(app, COMMON_HEATER, 0.9)
    [ev] = _feed(app, SALA_PLUG, 2000, fx.T0, 31)
    assert ev.data.appliance_id == COMMON_HEATER


def test_aparelho_pessoal_ou_pouco_provavel_nao_e_nomeado(app):
    _devices(app)
    personal = stable_id("appliance", "aquecedor-pessoal")
    _appliance(app, personal, "Aquecedor do Bruno", "personal", owner=fx.BRUNO)
    _ongoing(app, personal, 0.95)
    [ev] = _feed(app, SALA_PLUG, 2000, fx.T0, 31)
    assert ev.data.appliance_id is None

    _appliance(app, COMMON_HEATER, "Aquecedor da sala", "common")
    app.state.db.run_sync(lambda c: c.execute("DELETE FROM billing_consumption"))
    _ongoing(app, COMMON_HEATER, 0.6, name="incerto")
    [ev] = _feed(app, SALA_PLUG, 2000, fx.T0 + timedelta(hours=3), 31)
    assert ev.data.appliance_id is None


def _wait(predicate, what, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu a tempo: {what}")


def test_do_barramento_ao_aviso_da_casa(app, client):
    """Leituras no barramento -> `alerts.alert_raised` -> aviso `peak_alert` para os moradores;
    o senhorio não o vê (allow-list só `info`)."""
    _devices(app)
    _appliance(app, COMMON_HEATER, "Aquecedor da sala", "common")
    _ongoing(app, COMMON_HEATER, 0.9)
    for i in range(63):  # 31 min
        r = _reading(SALA_PLUG, 2000, fx.T0 + i * STEP)
        app.state.bus.publish_threadsafe(
            de.EnergyReadingRecorded(
                id=stable_id("ev", str(r.id)),
                ts=r.ts,
                household_id=fx.HOUSEHOLD,
                provenance=r.provenance,
                data=r,
            )
        )
    url = f"/api/households/{fx.HOUSEHOLD}/notifications"

    def peaks_for(sub):
        r = client.get(url, headers={"x-test-sub": sub})
        assert r.status_code == 200
        return [n for n in r.json() if n["kind"] == "peak_alert"]

    [n] = _wait(lambda: peaks_for("sub-ana"), "aviso de pico")
    assert n["title"] == "Pico de consumo na zona «Sala»"
    assert n["body"] == (
        "A zona «Sala» está a gastar 2,0 kW há 30 min. Provavelmente: Aquecedor da sala."
        " (SIMULADO)"
    )
    assert peaks_for("sub-senhorio") == []
