"""Runtime: leituras publicadas no barramento real viram sessões; RBAC da leitura."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.devices import PowerUnit
from homemind.contracts.domain_events import EnergyConsumptionClosed, EnergyReadingRecorded
from homemind.contracts.energy import (
    ApplianceMatch,
    ConsumptionEvent,
    ConsumptionStatus,
    LocationKind,
    ReadingStatus,
)
from homemind.core.events import append_event
from homemind.demo.scenario import events as scenario_events
from homemind.features.energy.router import _coverage, _overview
from homemind.features.energy.tests.test_consumer import MemoryCatalog

URL = "/api/households/{}/energy/overview"


def _house():
    from homemind.contracts import fixtures as fx

    return str(fx.HOUSEHOLD)


def _publish_readings(app):
    bus = app.state.bus
    readings = [e for e in scenario_events() if e.type == "energy.reading_recorded"]
    for e in readings:
        app.state.db.run_sync(lambda c, e=e: append_event(c, e))
    bus._loop.call_soon_threadsafe(bus._wake)


def _wait_sessions(client, sub, expected_min=1, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(URL.format(_house()), headers={"x-test-sub": sub})
        if r.status_code == 200 and len(r.json()["sessions"]) >= expected_min:
            return r.json()
        time.sleep(0.1)
    return client.get(URL.format(_house()), headers={"x-test-sub": sub}).json()


def test_tenant_sees_meter_and_sessions_unidentified(app, client):
    _publish_readings(app)
    body = _wait_sessions(client, "sub-ana")
    assert body["meters"], "última leitura por tomada"
    assert body["sessions"], "o consumidor corre no runtime"
    # Sem assinatura no catálogo, nada é identificado nem tem custo inventado.
    assert all(s["appliance_id"] is None and s["cost_cents"] is None for s in body["sessions"])
    assert all(s["provenance"]["origin"] == "simulated" for s in body["sessions"])


@pytest.mark.parametrize("sub", ["sub-senhorio", "sub-operador"])
def test_landlord_and_operator_never_get_readings(app, client, sub):
    _publish_readings(app)
    r = client.get(URL.format(_house()), headers={"x-test-sub": sub})
    assert r.status_code == 403
    assert "meters" not in r.text
    assert "coverage" not in r.text
    assert "declared_room_id" not in r.text


def test_other_household_is_denied(app, client):
    from homemind.features.households.tests.conftest import HOUSE_B

    r = client.get(URL.format(HOUSE_B), headers={"x-test-sub": "sub-ana"})
    assert r.status_code in (403, 404)


def test_unauthenticated(client):
    assert client.get(URL.format(_house())).status_code == 401


def test_catalog_vem_de_app_state_sem_import_cruzado(app):
    assert app.state.appliance_catalog is not None


def _reading_at(conn, at, watts, status=ReadingStatus.ok, observed_at=None):
    reading = replace(
        fx.reading(0, at),
        id=stable_id("coverage-reading", at.isoformat()),
        power_w=watts,
        status=status,
        raw_unit=PowerUnit.unknown if status is ReadingStatus.unit_unknown else PowerUnit.W,
        observed_at=observed_at,
    )
    append_event(
        conn,
        EnergyReadingRecorded(
            id=reading.id,
            ts=at,
            household_id=fx.HOUSEHOLD,
            correlation_id=fx.CORRELATION,
            provenance=reading.provenance,
            data=reading,
        ),
    )


def _session_at(conn, start, end, wh, location, *, identified=False, name="session"):
    session = ConsumptionEvent(
        id=stable_id("coverage-session", name),
        household_id=fx.HOUSEHOLD,
        device_id=fx.METER,
        match=(
            ApplianceMatch(appliance_id=fx.HEATER, confidence=1) if identified else ApplianceMatch()
        ),
        started_at=start,
        ended_at=end,
        status=ConsumptionStatus.closed,
        peak_w=3600,
        energy_wh=wh,
        location=location,
        room_id=fx.ROOM_SALA if location is LocationKind.common else None,
        provenance=fx.SIM_MEASURED,
    )
    append_event(
        conn,
        EnergyConsumptionClosed(
            id=stable_id("coverage-closed", name),
            ts=end,
            household_id=fx.HOUSEHOLD,
            correlation_id=session.id,
            provenance=session.provenance,
            data=session,
        ),
    )


@pytest.mark.parametrize(
    "gap", [ReadingStatus.missing, ReadingStatus.stale, ReadingStatus.unit_unknown]
)
def test_monthly_coverage_closes_and_declared_room_is_only_a_hint(db, gap):
    def check(conn):
        for seconds, watts, status in [
            (0, 3600, ReadingStatus.ok),
            (100, 3600, ReadingStatus.ok),
            (200, None, gap),
            (300, 3600, ReadingStatus.ok),
            (400, 3600, ReadingStatus.ok),
        ]:
            _reading_at(conn, fx.T0 + timedelta(seconds=seconds), watts, status)
        end = fx.T0 + timedelta(seconds=100)
        _session_at(conn, fx.T0, end, 50, LocationKind.common, name="measured")
        _session_at(conn, fx.T0, end, 50, LocationKind.unknown, identified=True, name="inferred")
        catalog = MemoryCatalog({}, {fx.HEATER: fx.heater().ownership})
        body = _overview(conn, fx.HOUSEHOLD, fx.T0 + timedelta(seconds=400), catalog)
        coverage = body.coverage
        assert (coverage.total_wh, coverage.measured_wh, coverage.inferred_wh) == (200, 50, 50)
        assert coverage.unattributed_wh == 100
        assert (
            coverage.measured_wh + coverage.inferred_wh + coverage.unattributed_wh
            == coverage.total_wh
        )
        assert (
            coverage.measured_percent + coverage.inferred_percent + coverage.unattributed_percent
            == 100
        )
        assert coverage.status == "ok" and not coverage.adjusted
        assert coverage.provenance == [fx.SIM_MEASURED]
        inferred = next(s for s in body.sessions if s.appliance_id)
        assert inferred.location == "unknown"
        assert inferred.declared_room_id == fx.ROOM_BRUNO
        assert next(s for s in body.sessions if not s.appliance_id).declared_room_id is None

    db.run_sync(check)


def test_coverage_empty_is_explicit_and_percentages_are_zero(db):
    coverage = db.run_sync(lambda c: _coverage(c, fx.HOUSEHOLD, fx.T0))
    assert coverage.status == "no_data"
    assert (
        coverage.total_wh
        == coverage.measured_wh
        == coverage.inferred_wh
        == coverage.unattributed_wh
        == 0
    )
    assert (
        coverage.measured_percent == coverage.inferred_percent == coverage.unattributed_percent == 0
    )


def test_coverage_reconciles_excess_session_rounding(db):
    def check(conn):
        end = fx.T0 + timedelta(seconds=1)
        _reading_at(conn, fx.T0, 3600)
        _reading_at(conn, end, 0)
        _session_at(conn, fx.T0, end, 1, LocationKind.common, name="measured")
        _session_at(conn, fx.T0, end, 1, LocationKind.unknown, identified=True, name="inferred")
        coverage = _coverage(conn, fx.HOUSEHOLD, end)
        assert coverage.total_wh == 1
        assert (coverage.measured_wh, coverage.inferred_wh, coverage.unattributed_wh) == (1, 0, 0)
        assert coverage.measured_percent + coverage.inferred_percent == 100
        assert coverage.adjusted

    db.run_sync(check)


def test_coverage_uses_local_month_and_prorates_crossing_sessions(db):
    def check(conn):
        conn.execute(
            "UPDATE household SET timezone='Pacific/Auckland' WHERE id=?", (str(fx.HOUSEHOLD),)
        )
        start = datetime(2026, 10, 31, 11, tzinfo=UTC)  # Local midnight, November 1.
        before, end = start - timedelta(seconds=100), start + timedelta(seconds=100)
        _reading_at(conn, before, 3600)
        _reading_at(conn, end, 3600)
        _session_at(conn, before, end, 200, LocationKind.common)
        coverage = _coverage(conn, fx.HOUSEHOLD, end)
        assert coverage.period_start == start
        assert coverage.total_wh == coverage.measured_wh == 100
        assert coverage.measured_percent == 100

    db.run_sync(check)


def test_coverage_is_not_limited_to_recent_500_events_or_20_sessions(db):
    def check(conn):
        for seconds in range(502):
            _reading_at(conn, fx.T0 + timedelta(seconds=seconds), 3600)
        for i in range(21):
            _session_at(
                conn,
                fx.T0,
                fx.T0 + timedelta(seconds=1),
                1,
                LocationKind.common,
                name=str(i),
            )
        coverage = _coverage(conn, fx.HOUSEHOLD, fx.T0 + timedelta(seconds=501))
        assert coverage.total_wh == 501
        assert coverage.measured_wh == 21
        assert coverage.unattributed_wh == 480

    db.run_sync(check)


def test_coverage_stale_repeated_observation_and_no_tail_extrapolation(db):
    def check(conn):
        _reading_at(conn, fx.T0, 3600)
        _reading_at(conn, fx.T0 + timedelta(seconds=100), 3600)
        _reading_at(
            conn,
            fx.T0 + timedelta(seconds=200),
            3600,
            ReadingStatus.stale,
            observed_at=fx.T0 + timedelta(seconds=100),
        )
        _reading_at(conn, fx.T0 + timedelta(seconds=300), 3600)
        coverage = _coverage(conn, fx.HOUSEHOLD, fx.T0 + timedelta(seconds=900))
        assert coverage.total_wh == coverage.unattributed_wh == 100

    db.run_sync(check)


def test_overview_serializes_coverage_and_declared_hint(app, client, now, monkeypatch):
    end = fx.T0 + timedelta(seconds=100)
    now["value"] = end
    monkeypatch.setattr(
        app.state, "appliance_catalog", MemoryCatalog({}, {fx.HEATER: fx.heater().ownership})
    )

    def setup(conn):
        _reading_at(conn, fx.T0, 3600)
        _reading_at(conn, end, 0)
        _session_at(conn, fx.T0, end, 40, LocationKind.unknown, identified=True)

    app.state.db.run_sync(setup)
    response = client.get(URL.format(_house()), headers={"x-test-sub": "sub-ana"})
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["total_wh"] == 100
    assert body["coverage"]["inferred_wh"] == 40
    assert body["coverage"]["unattributed_wh"] == 60
    session = next(s for s in body["sessions"] if s["appliance_id"] == str(fx.HEATER))
    assert session["location"] == "unknown"
    assert session["declared_room_id"] == str(fx.ROOM_BRUNO)


@pytest.mark.parametrize(
    "seconds,expected_wh,expected_percent",
    [(3.5, (1, 1, 2), (25, 25, 50)), (3, (1, 1, 1), (34, 33, 33))],
)
def test_coverage_rounds_total_once_and_reconciles_percent_remainders(
    db, seconds, expected_wh, expected_percent
):
    def check(conn):
        # 3.5 Wh rounds to the even integer 4; Wh and percentages both close.
        end = fx.T0 + timedelta(seconds=seconds)
        _reading_at(conn, fx.T0, 3600)
        _reading_at(conn, end, 0)
        _session_at(conn, fx.T0, end, 1, LocationKind.common, name="measured")
        _session_at(conn, fx.T0, end, 1, LocationKind.unknown, identified=True, name="inferred")
        coverage = _coverage(conn, fx.HOUSEHOLD, end)
        assert coverage.total_wh == sum(expected_wh)
        assert (
            coverage.measured_wh,
            coverage.inferred_wh,
            coverage.unattributed_wh,
        ) == expected_wh
        assert (
            coverage.measured_percent,
            coverage.inferred_percent,
            coverage.unattributed_percent,
        ) == expected_percent
        assert not coverage.adjusted

    db.run_sync(check)
