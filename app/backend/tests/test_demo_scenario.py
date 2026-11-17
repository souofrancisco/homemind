"""Contrato da DEMO-01: zero hardware, idempotência, isolamento e resultados de referência."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from homemind.contracts import billing, fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import MatchOutcome, ReadingStatus
from homemind.core.db import Database
from homemind.demo.cli import FILE_NAME, DemoSafetyError, DemoStore
from homemind.demo.scenario import CLOCK, POWER_PROFILE, events, power_samples, references
from homemind.features.households.repo import insert_household


@pytest.fixture
def store(tmp_path: Path) -> DemoStore:
    return DemoStore(tmp_path / "private-demo")


def test_deterministic_clock_samples_and_events():
    assert CLOCK.at(1) > CLOCK.at(0)
    assert [(s.ts, s.power_w) for s in power_samples()] == [
        (CLOCK.at(t), watts) for t, watts in POWER_PROFILE
    ]
    first, second = events(), events()
    assert first == second
    assert [e.id for e in first] == [e.id for e in second]
    assert len({e.id for e in first}) == len(first)
    assert all(e.provenance.simulated for e in first)


def test_presence_is_anonymous_and_confirmation_is_human():
    timeline = events()
    doors = [e for e in timeline if e.type == "presence.door_crossed"]
    assert len(doors) == 2
    assert [e.data.direction.value for e in doors] == ["in", "out"]
    assert all("resident_id" not in e.data.model_dump() for e in doors)
    assert not any(e.type == "presence.changed" for e in timeline)
    answered = next(e for e in timeline if e.type == "notification.responded")
    assert answered.data.response.resident_id == fx.CARLA
    attributed = next(e for e in timeline if e.type == "billing.attribution_changed")
    assert attributed.data.decided_by.by_resident_id == fx.CARLA
    assert attributed.data.consumption_event_id == fx.CONSUMPTION


def test_identified_ambiguous_unknown_do_not_become_identity():
    closed = [e.data for e in events() if e.type == "energy.consumption_closed"]
    assert [c.match.outcome for c in closed] == [
        MatchOutcome.identified,
        MatchOutcome.identified,
        MatchOutcome.unknown,
        MatchOutcome.ambiguous,
    ]
    assert closed[2].match.appliance_id is None
    assert closed[3].match.appliance_id is None
    assert closed[1].match.appliance_id == fx.HEATER
    assert not any("resident_id" in c.model_dump() for c in closed)


def test_sensor_failure_is_not_0_w_and_never_requires_hardware():
    last = next(
        e
        for e in events()
        if e.type == "energy.reading_recorded" and e.data.id == stable_id("demo-reading", "missing")
    )
    assert last.data.status is ReadingStatus.missing
    assert last.data.power_w is None
    assert not last.data.usable


def test_bills_are_distinct_reference_fixtures():
    a, rows_a = fx.bill_a()
    b, rows_b = fx.bill_b()
    billing.validate_allocations(a, rows_a)
    billing.validate_allocations(b, rows_b)
    assert [x.amount_cents for x in rows_a] == [4512, 2976, 2464, 2048]
    assert [x.amount_cents for x in rows_b] == [4680, 2760, 2440, 2120]
    assert a.id != b.id
    assert sum(x.amount_cents for x in rows_a) == 12_000
    assert sum(x.amount_cents for x in rows_b) == 12_000
    assert len([x for x in references() if x[0] == "reference_bill"]) == 2


def test_two_resets_same_semantic_state(store):
    first = store.reset()
    second = store.reset()
    assert first == second
    assert first["households"] == 1
    assert first["tenants"] == 4
    assert first["events"] == len(events())
    assert first["backend_ui_integrated"] is False


def test_prepare_and_repeat_replay_do_not_duplicate(store):
    original = store.prepare()
    assert store.prepare() == original
    assert store.replay() == original
    assert store.replay() == original


def test_application_database_reopen_preserves_demo(store):
    original = store.prepare()
    db = Database(store.path)
    db.open()
    db.close()
    assert store.verify() == original


def test_existing_unmarked_sqlite_refused_and_preserved(store):
    store.root.mkdir()
    with sqlite3.connect(store.path) as conn:
        conn.execute("CREATE TABLE important_real_data (value TEXT)")
        conn.execute("INSERT INTO important_real_data VALUES ('preserve')")
    with pytest.raises(DemoSafetyError):
        store.reset()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT value FROM important_real_data").fetchone()[0] == "preserve"


def test_foreign_household_is_not_erased(store):
    store.prepare()
    db = Database(store.path)
    db.open()
    foreign = stable_id("household", "other-not-demo")
    db.run_sync(
        lambda conn: insert_household(
            conn,
            replace(fx.household(), id=foreign, name="Casa protegida"),
        )
    )
    db.close()
    with pytest.raises(DemoSafetyError):
        store.reset()
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute("SELECT count(*) FROM household WHERE id=?", (str(foreign),)).fetchone()[0]
            == 1
        )


def test_symlink_and_hardlink_are_never_reset(store, tmp_path):
    store.root.mkdir()
    original = tmp_path / "untouched.sqlite3"
    original.write_bytes(b"untouched")
    store.path.symlink_to(original)
    with pytest.raises(DemoSafetyError):
        store.reset()
    assert original.read_bytes() == b"untouched"
    store.path.unlink()
    # A hardlink com uma base alheia também não pode ser substituída.
    store.prepare()
    original.unlink()
    store.path.rename(original)
    os.link(original, store.path)
    with pytest.raises(DemoSafetyError):
        store.reset()
    assert original.exists()


def test_only_dedicated_filename_is_used(store):
    store.prepare()
    assert store.path == store.root / FILE_NAME
    assert not (store.root / "application.sqlite3").exists()
