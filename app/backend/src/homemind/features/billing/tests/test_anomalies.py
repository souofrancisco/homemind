"""Gasto anormal nas zonas comuns (ALERT-03): o dia de hoje ≥ 2× o habitual e ≥ 1 kWh a mais.

Casa demo SIMULADA (Europe/Lisbon = UTC em novembro); leituras de 5 em 5 min. A 100 W um dia
inteiro são 2,4 kWh."""

import time
from datetime import UTC, datetime, timedelta

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import ReadingStatus
from homemind.features.billing import anomalies

SALA_PLUG = stable_id("device", "tomada-sala")
QUARTO_PLUG = stable_id("device", "tomada-quarto-ana")
SALA_METER = stable_id("device", "contador-geral")
LOOSE_PLUG = stable_id("device", "tomada-sem-divisao")
STEP = timedelta(minutes=5)
D0 = datetime(2026, 11, 10, tzinfo=UTC)  # 3 dias de histórico; o 4.º (13/11) é «hoje»
HOJE = D0 + timedelta(days=3)


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


def _reading(device, watts, at):
    return replace(
        fx.reading(watts, at),
        id=stable_id("reading", str(device), at.isoformat()),
        device_id=device,
    )


def _feed(app, device, watts, start, hours):
    """Leituras de 5 em 5 min durante `hours` a partir de `start`; devolve os eventos."""
    out = []
    for i in range(int(hours * 12)):
        r = _reading(device, watts, start + i * STEP)
        out += app.state.db.run_sync(lambda c, r=r: anomalies.observe(c, fx.HOUSEHOLD, r))
    return out


def _historico(app, device=SALA_PLUG, watts=100, days=3):
    assert _feed(app, device, watts, D0, 24 * days) == []


def _dia(app, device, day):
    row = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT energy_wh, covered_s FROM alerts_device_day WHERE device_id = ? AND day = ?",
            (str(device), day),
        ).fetchone()
    )
    return (round(row["energy_wh"]), row["covered_s"]) if row else None


def test_dia_fora_do_habitual_avisa_uma_vez(app):
    _devices(app)
    _historico(app)
    assert _dia(app, SALA_PLUG, "2026-11-11") == (2400, 86_400)
    # hoje a 300 W: 25 Wh por leitura; chega a 4,8 kWh (2× o habitual) ao fim de ~16 h
    assert _feed(app, SALA_PLUG, 300, HOJE, 15) == []
    [ev] = _feed(app, SALA_PLUG, 300, HOJE + timedelta(hours=15), 2)
    assert isinstance(ev, de.AlertsAlertRaised) and ev.provenance.simulated
    d = ev.data
    assert (d.kind, d.severity.value) == (de.AlertKind.anomaly, "warning")
    assert (d.device_id, d.room_id, d.day) == (SALA_PLUG, fx.ROOM_SALA, HOJE.date())
    assert d.baseline_wh == 2400 and 4800 <= d.energy_wh < 4800 + 25
    # o resto do dia não repete; no dia seguinte volta a poder avisar
    assert _feed(app, SALA_PLUG, 300, HOJE + timedelta(hours=17), 7) == []
    assert ev.id == stable_id("alerts.anomaly", str(SALA_PLUG), "2026-11-13")


def test_sem_dias_suficientes_bem_medidos_nao_ha_habitual(app):
    """Dois dias completos e um com lacuna (só 10 h de leituras): não se inventa um habitual."""
    _devices(app)
    _historico(app, days=2)
    assert _feed(app, SALA_PLUG, 100, D0 + timedelta(days=2), 10) == []
    assert _dia(app, SALA_PLUG, "2026-11-12")[1] < 20 * 3600
    assert _feed(app, SALA_PLUG, 2000, HOJE, 24) == []


def test_pouco_acima_em_valor_absoluto_nao_avisa(app):
    """10 W habituais (240 Wh/dia) e hoje 30 W (720 Wh): 3× mais, mas < 1 kWh a mais."""
    _devices(app)
    _historico(app, watts=10)
    assert _feed(app, SALA_PLUG, 30, HOJE, 24) == []


def test_quartos_contadores_e_tomadas_sem_divisao_nunca_avisam(app):
    _devices(app)
    for device in (QUARTO_PLUG, SALA_METER, LOOSE_PLUG, stable_id("device", "nao-registada")):
        _historico(app, device=device)
        assert _feed(app, device, 2000, HOJE, 24) == []
        assert _dia(app, device, "2026-11-11") is None  # nem se guarda o dia


def test_lacunas_nao_sao_preenchidas_e_reentrega_nao_conta_duas_vezes(app):
    _devices(app)
    _feed(app, SALA_PLUG, 1000, D0, 1)  # 12 leituras: 11 intervalos de 5 min
    r = _reading(SALA_PLUG, 1000, D0 + timedelta(hours=1))
    for _ in range(2):  # a mesma leitura entregue duas vezes
        app.state.db.run_sync(lambda c: anomalies.observe(c, fx.HOUSEHOLD, r))
    assert _dia(app, SALA_PLUG, "2026-11-10") == (1000, 3600)
    # 30 min sem leituras (> MAX_GAP): esse intervalo não conta; leitura `missing` também não
    falta = replace(
        _reading(SALA_PLUG, 0, D0 + timedelta(hours=1, minutes=10)),
        status=ReadingStatus.missing,
        power_w=None,
    )
    assert app.state.db.run_sync(lambda c: anomalies.observe(c, fx.HOUSEHOLD, falta)) == []
    _feed(app, SALA_PLUG, 1000, D0 + timedelta(hours=1, minutes=30), 1 / 12)
    assert _dia(app, SALA_PLUG, "2026-11-10") == (1000, 3600)


def _wait(fn, what):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if value := fn():
            return value
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu a tempo: {what}")


def test_do_barramento_ao_aviso_dos_moradores(app, client):
    """Histórico e quase todo o dia já agregados; a leitura seguinte, pelo barramento, passa o
    limite -> `alerts.alert_raised` (`anomaly`) -> aviso aos moradores; o senhorio não o vê."""
    _devices(app)
    last = HOJE + timedelta(hours=12)

    def seed(conn):
        for i in range(3):
            day = (D0 + timedelta(days=i)).date().isoformat()
            conn.execute(
                "INSERT INTO alerts_device_day VALUES (?,?,?,?,?)",
                (str(fx.HOUSEHOLD), str(SALA_PLUG), day, 500.0, 86_400),
            )
        conn.execute(
            "INSERT INTO alerts_device_day VALUES (?,?,?,?,?)",
            (str(fx.HOUSEHOLD), str(SALA_PLUG), HOJE.date().isoformat(), 1_450.0, 43_200),
        )
        conn.execute(
            "INSERT INTO alerts_anomaly_state VALUES (?,?,?,?,NULL)",
            (str(fx.HOUSEHOLD), str(SALA_PLUG), last.isoformat(), 1_200.0),
        )

    app.state.db.run_sync(seed)
    r = _reading(SALA_PLUG, 1_200, last + STEP)  # +100 Wh -> 1550 Wh: ≥ 2 × 500 e ≥ +1 kWh
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

    def avisos(sub):
        res = client.get(url, headers={"x-test-sub": sub})
        assert res.status_code == 200
        return [n for n in res.json() if n["title"].startswith("Gasto fora do habitual")]

    [n] = _wait(lambda: avisos("sub-ana"), "aviso de gasto anormal")
    assert n["title"] == "Gasto fora do habitual na zona «Sala»"
    assert n["body"] == (
        "Hoje a zona «Sala» já gastou 1,6 kWh; num dia habitual gasta 0,5 kWh."
        " Vale a pena ver se ficou algo ligado. (SIMULADO)"
    )
    assert n["kind"] == "peak_alert" and n["severity"] == "warning"
    assert avisos("sub-senhorio") == []
