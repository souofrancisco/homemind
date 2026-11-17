"""PRIV-02: testes sem rede, câmara, coletores Wi-Fi nem sensores reais."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.presence import (
    DoorCrossed,
    PresenceEvent,
    PresenceSource,
    PresenceState,
)
from homemind.core.db import Database, migrate
from homemind.core.events import append_event
from homemind.features.households.tests.conftest import HOUSE_B, seed_two_houses
from homemind.features.presence.privacy import (
    automatic_state_when_sensor_unavailable,
    individual_cue_allowed,
    record_individual_cue,
)

NOW = datetime(2026, 11, 17, 21, tzinfo=UTC)


@pytest.fixture
def db():
    database = Database(":memory:")
    database.open()
    migrate(database)
    database.run_sync(seed_two_houses)
    yield database
    database.close()


def cue(*, resident=fx.ANA, house=fx.HOUSEHOLD, source=PresenceSource.wifi):
    return PresenceEvent(
        id=uuid4(),
        household_id=house,
        resident_id=resident,
        ts=NOW,
        state=PresenceState.home,
        source=source,
        confidence=0.8,
        provenance=fx.SIM_INFERRED,
    )


def set_opt_in(db, resident, house, enabled):
    db.run_sync(
        lambda conn: conn.execute(
            "UPDATE membership SET presence_opt_in = ?"
            " WHERE household_id = ? AND resident_id = ?",
            (int(enabled), str(house), str(resident)),
        )
    )


def allow(db, event, **kwargs):
    return db.run_sync(lambda conn: individual_cue_allowed(conn, event, now=NOW, **kwargs))


def test_wifi_off_by_default_even_after_opt_in(db):
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, True)
    assert allow(db, cue()) is False


def test_no_opt_in_no_individual_signal_even_if_wifi_flag_is_on(db):
    assert not allow(db, cue(), wifi_collection_enabled=True)
    assert not allow(db, cue(source=PresenceSource.manual), actor_resident_id=fx.ANA)


def test_revocation_blocks_future_wifi_and_manual_signals(db):
    event = cue()
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, True)
    assert not allow(db, event, wifi_collection_enabled=True)
    assert allow(db, cue(source=PresenceSource.manual), actor_resident_id=fx.ANA)
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, False)
    assert not allow(db, event, wifi_collection_enabled=True)
    assert not allow(db, cue(source=PresenceSource.manual), actor_resident_id=fx.ANA)
    count = db.run_sync(lambda c: c.execute("SELECT count(*) FROM domain_event").fetchone()[0])
    assert count == 0  # verificar permissões não cria histórico de presença


def test_record_manual_cue_is_gated_and_persisted_in_one_transaction(db):
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, True)
    event = cue(source=PresenceSource.manual)
    recorded = db.run_sync(
        lambda conn: record_individual_cue(conn, event, now=NOW, actor_resident_id=fx.ANA)
    )
    assert recorded is True
    stored = db.run_sync(
        lambda conn: conn.execute(
            "SELECT type, payload_json FROM domain_event WHERE id = ?", (str(event.id),)
        ).fetchone()
    )
    assert stored["type"] == "presence.cue_recorded"
    assert str(fx.ANA) in stored["payload_json"]


def test_record_denied_cue_does_not_persist_and_wifi_flag_cannot_bypass_device_opt_in(db):
    event = cue(source=PresenceSource.wifi)
    recorded = db.run_sync(
        lambda conn: record_individual_cue(
            conn, event, now=NOW, actor_resident_id=None, wifi_collection_enabled=True
        )
    )
    assert recorded is False
    count = db.run_sync(
        lambda conn: conn.execute("SELECT count(*) FROM domain_event").fetchone()[0]
    )
    assert count == 0


def test_record_cue_requires_database_transaction(db):
    event = cue(source=PresenceSource.manual)
    with db._lock:
        conn = db._conn
        assert conn is not None
        with pytest.raises(RuntimeError, match="transação"):
            record_individual_cue(conn, event, now=NOW, actor_resident_id=fx.ANA)


def test_manual_requires_same_authenticated_resident(db):
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, True)
    assert not allow(db, cue(source=PresenceSource.manual), actor_resident_id=fx.BRUNO)
    assert allow(db, cue(source=PresenceSource.manual), actor_resident_id=fx.ANA)


def test_isolation_household_role_ended_and_unknown_guest(db):
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, True)
    assert not allow(db, cue(house=HOUSE_B), wifi_collection_enabled=True)
    assert not allow(db, cue(resident=fx.LANDLORD), wifi_collection_enabled=True)
    assert not allow(db, cue(resident=uuid4()), wifi_collection_enabled=True)
    assert not allow(db, cue(resident=fx.ANA, house=uuid4()), wifi_collection_enabled=True)
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-16'"
            " WHERE household_id = ? AND resident_id = ?",
            (str(fx.HOUSEHOLD), str(fx.ANA)),
        )
    )
    assert not allow(db, cue(), wifi_collection_enabled=True)


def test_simulated_cue_cannot_enter_real_household(db):
    set_opt_in(db, fx.ANA, fx.HOUSEHOLD, True)
    db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET source_kind = 'real' WHERE id = ?",
            (str(fx.HOUSEHOLD),),
        )
    )
    assert not allow(db, cue(), wifi_collection_enabled=True)


def test_missing_sensor_is_unknown_not_away():
    assert (
        automatic_state_when_sensor_unavailable(PresenceState.away, sensor_available=False)
        is PresenceState.uncertain
    )
    assert (
        automatic_state_when_sensor_unavailable(PresenceState.home, sensor_available=False)
        is PresenceState.uncertain
    )
    assert (
        automatic_state_when_sensor_unavailable(PresenceState.home, sensor_available=True)
        is PresenceState.home
    )


def test_wifi_never_reports_exit_and_camera_never_has_identity():
    data = cue().model_dump()
    data["state"] = PresenceState.away
    with pytest.raises(ValidationError):
        PresenceEvent.model_validate(data)
    invalid_door = fx.door_crossed().model_dump()
    invalid_door["resident_id"] = str(fx.ANA)
    with pytest.raises(ValidationError):
        DoorCrossed.model_validate(invalid_door)


def test_door_event_persistence_is_anonymous_and_simulated(db):
    event = de.PresenceDoorCrossed(
        id=uuid4(),
        correlation_id=uuid4(),
        ts=fx.T0,
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_INFERRED,
        data=fx.door_crossed(),
    )
    db.run_sync(lambda conn: append_event(conn, event))
    stored = db.run_sync(
        lambda c: c.execute("SELECT type, origin, kind, payload_json FROM domain_event").fetchone()
    )
    assert stored["type"] == "presence.door_crossed"
    assert stored["origin"] == "simulated"
    assert stored["kind"] == "inferred"
    assert all(
        forbidden not in stored["payload_json"].lower()
        for forbidden in ("frame", "image", "face", "resident_id", "track_id", "ssid", "mac")
    )
