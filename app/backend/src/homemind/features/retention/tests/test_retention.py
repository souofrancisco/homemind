"""PRIV-04: retenção por categoria. A telemetria expira; a evidência financeira nunca se apaga."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.core.config import Settings
from homemind.core.events import append_event
from homemind.features.retention import purge as rp
from homemind.features.retention.policy import EVENT_CATEGORY, PURGEABLE_EVENT_TYPES, Category

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
OLD = NOW - timedelta(days=120)
RECENT = NOW - timedelta(days=10)


def test_todos_os_tipos_de_evento_tem_categoria():
    """Um tipo de evento novo tem de ser classificado aqui antes de existir."""
    assert set(de.EVENT_TYPES) == set(EVENT_CATEGORY), set(de.EVENT_TYPES) ^ set(EVENT_CATEGORY)
    assert set(PURGEABLE_EVENT_TYPES) == {"energy.reading_recorded", "sensor.reading_recorded"}


def test_prazo_configuravel_com_minimo_de_dois_meses():
    assert Settings().retention_telemetry_days == 90
    assert Settings(retention_telemetry_days=0).retention_telemetry_days == 0
    with pytest.raises(ValueError, match="62"):
        Settings(retention_telemetry_days=30)


def _reading(at, name):
    r = replace(fx.reading(800, at), id=stable_id("reading", name))
    return de.EnergyReadingRecorded(
        id=stable_id("ev", name), ts=at, household_id=fx.HOUSEHOLD, provenance=r.provenance, data=r
    )


def _financial(at, name):
    c = replace(fx.consumption(closed=True), id=stable_id("consumption", name))
    return de.EnergyConsumptionClosed(
        id=stable_id("ev", name), ts=at, household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c
    )


def _types(app):
    return app.state.db.run_sync(
        lambda c: sorted(r["type"] for r in c.execute("SELECT type FROM domain_event"))
    )


def _seed(app):
    def work(conn):
        for ev in (
            _reading(OLD, "velha"),
            _reading(RECENT, "recente"),
            _financial(OLD, "consumo-velho"),
        ):
            append_event(conn, ev)
        conn.execute(
            "INSERT INTO processed_event VALUES (?,?,?)",
            ("billing.peaks", str(stable_id("ev", "velha")), NOW.isoformat()),
        )
        for day in ("2026-07-01", "2026-11-17"):
            conn.execute(
                "INSERT INTO alerts_device_day VALUES (?,?,?,?,?)",
                (str(fx.HOUSEHOLD), str(stable_id("device", "tomada-sala")), day, 10.0, 600),
            )
        conn.execute(
            "INSERT INTO alerts_room_night VALUES (?,?,?,?,?,?)",
            (str(fx.HOUSEHOLD), str(fx.ROOM_ANA), "2026-07-01", 17.0, 1, 1),
        )

    app.state.db.run_sync(work)


def test_expurgo_apaga_so_telemetria_e_agregados_expirados(app):
    _seed(app)
    done = rp.purge(app.state.db.run_sync, NOW, 90)
    assert done == rp.Purged(events=1, aggregates=2)
    assert _types(app) == ["energy.consumption_closed", "energy.reading_recorded"]
    left = app.state.db.run_sync(
        lambda c: [r["id"] for r in c.execute("SELECT id FROM domain_event")]
    )
    assert str(stable_id("ev", "velha")) not in left
    marks = app.state.db.run_sync(lambda c: c.execute("SELECT * FROM processed_event").fetchall())
    assert str(stable_id("ev", "velha")) not in [m["event_id"] for m in marks]
    days = app.state.db.run_sync(
        lambda c: [r["day"] for r in c.execute("SELECT day FROM alerts_device_day")]
    )
    assert days == ["2026-11-17"]
    # repetir não faz nada; retenção 0 = desligada
    assert rp.purge(app.state.db.run_sync, NOW, 90) == rp.Purged()
    assert rp.purge(app.state.db.run_sync, NOW + timedelta(days=999), 0) == rp.Purged()


def test_evento_ainda_a_ser_tentado_nao_se_apaga(app):
    _seed(app)
    app.state.db.run_sync(
        lambda c: c.execute(
            "INSERT INTO event_failure VALUES (?,?,?,?,0,?)",
            ("billing.peaks", str(stable_id("ev", "velha")), 2, "ValueError", NOW.isoformat()),
        )
    )
    assert rp.purge(app.state.db.run_sync, NOW, 90).events == 0


def test_lotes_continuam_ate_ao_fim(app, monkeypatch):
    monkeypatch.setattr(rp, "BATCH", 2)
    app.state.db.run_sync(
        lambda c: [append_event(c, _reading(OLD + timedelta(minutes=i), f"r{i}")) for i in range(5)]
    )
    assert rp.purge(app.state.db.run_sync, NOW, 90).events == 5
    assert _types(app) == []


def test_a_base_de_dados_recusa_apagar_evidencia_financeira(app):
    """Mesmo um DELETE direto (bug, script) não apaga consumos, votos, faturas ou presença."""
    _seed(app)
    with pytest.raises(sqlite3.IntegrityError, match="imutável"):
        app.state.db.run_sync(
            lambda c: c.execute("DELETE FROM domain_event WHERE type = 'energy.consumption_closed'")
        )
    with pytest.raises(sqlite3.IntegrityError, match="imutável"):
        app.state.db.run_sync(lambda c: c.execute("UPDATE domain_event SET type = 'x'"))
    assert Category.financial is EVENT_CATEGORY["notification.responded"]
