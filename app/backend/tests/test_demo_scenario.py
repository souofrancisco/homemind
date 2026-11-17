"""Contrato da DEMO-01: zero hardware, idempotência, isolamento e resultados de referência."""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from homemind.contracts import billing
from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import MatchOutcome, ReadingStatus
from homemind.contracts.notification import ConfirmationVerdict, Notification
from homemind.core.db import MIGRATIONS_DIR, Database
from homemind.core.events import EventBus, append_event, load_events
from homemind.demo.cli import FILE_NAME, DemoSafetyError, DemoStore
from homemind.demo.scenario import CLOCK, POWER_PROFILE, events, power_samples, references
from homemind.features.households.repo import insert_household
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.handlers import (
    CONFIRMATION_CONSUMER,
    CONFIRMATION_EVENT_TYPES,
    make_confirmation_handler,
)
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository


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


def test_presence_is_anonymous_and_confirmation_is_only_a_p3_input():
    timeline = events()
    doors = [e for e in timeline if e.type == "presence.door_crossed"]
    assert len(doors) == 2
    assert [e.data.direction.value for e in doors] == ["in", "out"]
    assert all("resident_id" not in e.data.model_dump() for e in doors)
    assert not any(e.type == "presence.changed" for e in timeline)
    assert sum(e.type == "billing.confirmation_needed" for e in timeline) == 1
    assert not any(e.type in {"notification.created", "notification.responded"} for e in timeline)
    assert not any(e.type == "billing.attribution_changed" for e in timeline)


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
    zero = next(
        e for e in events() if e.type == "energy.reading_recorded" and e.data.ts == CLOCK.at(159)
    )
    assert zero.data.status is ReadingStatus.ok
    assert zero.data.power_w == 0
    assert zero.data.usable


def test_ongoing_consumption_has_unknown_energy_not_zero():
    ongoing = [e.data for e in events() if e.type == "energy.consumption_detected"]
    assert len(ongoing) == 4
    assert all(item.energy_wh is None and item.cost_estimate is None for item in ongoing)


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


def test_prepare_applies_all_current_main_migrations(store):
    store.prepare()
    expected = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
    with sqlite3.connect(store.path) as conn:
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migration")}
    assert applied == expected
    assert {"0003_core_membership_invitations.sql", "0100_billing_bills.sql"} <= applied
    assert {
        "0101_house_appliance_catalog.sql",
        "0102_house_appliance_temporal_guards.sql",
    } <= applied
    assert {"0200_presence_tables.sql", "0300_notifications_core.sql"} <= applied


def test_prepare_upgrades_existing_demo_to_new_migrations(store, tmp_path, monkeypatch):
    from homemind.core import db as core_db

    current_migrations = core_db.MIGRATIONS_DIR
    old_migrations = tmp_path / "older-migrations"
    old_migrations.mkdir()
    for name in (
        "0001_core_households.sql",
        "0002_core_events.sql",
        "0003_core_membership_invitations.sql",
        "0100_billing_bills.sql",
    ):
        shutil.copyfile(current_migrations / name, old_migrations / name)
    monkeypatch.setattr(core_db, "MIGRATIONS_DIR", old_migrations)
    store.prepare()
    with sqlite3.connect(store.path) as conn:
        old_applied = {row[0] for row in conn.execute("SELECT name FROM schema_migration")}
    assert old_applied == {path.name for path in old_migrations.glob("*.sql")}

    monkeypatch.setattr(core_db, "MIGRATIONS_DIR", current_migrations)
    store.prepare()
    with sqlite3.connect(store.path) as conn:
        upgraded = {row[0] for row in conn.execute("SELECT name FROM schema_migration")}
    assert upgraded == {path.name for path in current_migrations.glob("*.sql")}


def test_replay_crash_rolls_back_and_can_be_retried(store, monkeypatch):
    expected = store.prepare()
    from homemind.demo import cli

    real_append = cli.append_event
    calls = 0

    def crash_after_some_events(conn, event):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("simulated replay crash")
        return real_append(conn, event)

    monkeypatch.setattr(cli, "append_event", crash_after_some_events)
    with pytest.raises(RuntimeError, match="simulated replay crash"):
        store.replay()
    assert store.verify() == expected
    monkeypatch.setattr(cli, "append_event", real_append)
    assert store.replay() == expected


def test_process_crash_leaves_recoverable_wal_and_replay_recovers(store):
    expected = store.prepare()
    script = """
import os
import sys
from pathlib import Path
from homemind.demo import cli
from homemind.demo.cli import DemoStore

real_append = cli.append_event
calls = 0
def crash(conn, event):
    global calls
    calls += 1
    if calls == 4:
        os._exit(73)
    return real_append(conn, event)
cli.append_event = crash
DemoStore(Path(sys.argv[1])).replay()
"""
    backend_src = Path(__file__).parents[1] / "src"
    env = {**os.environ, "PYTHONPATH": str(backend_src)}
    child = subprocess.run([sys.executable, "-c", script, str(store.root)], env=env, check=False)
    assert child.returncode == 73
    assert Path(f"{store.path}-wal").exists()
    assert store.replay() == expected
    assert not Path(f"{store.path}-wal").exists()
    assert not Path(f"{store.path}-shm").exists()


def test_real_p3_consumer_and_d32_votes_use_demo_input(store):
    store.prepare()
    db = Database(store.path)
    db.open()
    try:
        confirmation = next(
            row
            for row in db.run_sync(load_events)
            if row.event.type == "billing.confirmation_needed"
        )
        bus = EventBus(db)
        bus.subscribe(
            CONFIRMATION_CONSUMER,
            make_confirmation_handler(lambda: CLOCK.at(132)),
            CONFIRMATION_EVENT_TYPES,
        )
        assert asyncio.run(bus.deliver(CONFIRMATION_CONSUMER, confirmation))
        assert not asyncio.run(bus.deliver(CONFIRMATION_CONSUMER, confirmation))
        notification_row = db.run_sync(
            lambda conn: conn.execute("SELECT json FROM notification").fetchone()
        )
        notification_id = Notification.model_validate_json(notification_row[0]).id

        def cast_vote(resident_id, action_id, target_resident_id=None):
            def work(conn):
                service = NotificationService(
                    SqliteNotificationRepository(conn),
                    SqliteResidentDirectory(conn),
                    lambda: CLOCK.at(133),
                )
                outcome = service.respond(
                    notification_id,
                    household_id=fx.HOUSEHOLD,
                    resident_id=resident_id,
                    action_id=action_id,
                    target_resident_id=target_resident_id,
                )
                for event in outcome.events:
                    append_event(conn, event)
                return outcome

            return db.run_sync(work)

        first = cast_vote(fx.ANA, "other", fx.BRUNO)
        second = cast_vote(fx.CARLA, "unknown")
        third = cast_vote(fx.DIOGO, "other", fx.BRUNO)
        outcomes = [outcome.events[0].data.outcome.verdict for outcome in (first, second, third)]
        assert outcomes == [
            ConfirmationVerdict.pending,
            ConfirmationVerdict.pending,
            ConfirmationVerdict.accusation_accepted,
        ]
        voters = [outcome.events[0].data.response.resident_id for outcome in (first, second, third)]
        assert voters == [fx.ANA, fx.CARLA, fx.DIOGO]
        notifications = db.run_sync(
            lambda conn: conn.execute("SELECT json FROM notification").fetchall()
        )
        assert len(notifications) == 1
        persisted = Notification.model_validate_json(notifications[0][0])
        assert persisted.status.value == "actioned"
        assert persisted.response.resident_id == fx.DIOGO
        assert [vote.resident_id for vote in persisted.responses] == [fx.ANA, fx.CARLA, fx.DIOGO]
    finally:
        db.close()


def test_readonly_marker_check_leaves_no_sqlite_sidecars(store):
    store.prepare()
    store._guard(existing=True)
    assert not Path(f"{store.path}-wal").exists()
    assert not Path(f"{store.path}-shm").exists()


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


def test_demo_reset_refuses_sidecars_even_when_database_is_missing(store):
    store.root.mkdir()
    wal = Path(f"{store.path}-wal")
    wal.write_bytes(b"unowned wal data")
    with pytest.raises(DemoSafetyError, match="WAL/SHM"):
        store.prepare()
    assert wal.read_bytes() == b"unowned wal data"
    assert not store.path.exists()


def test_demo_reset_refuses_symlinked_parent_path(store, tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    store_through_link = DemoStore(linked / "private")
    with pytest.raises(DemoSafetyError, match="symlink"):
        store_through_link.prepare()
    assert list(actual.iterdir()) == []


def test_demo_reset_refuses_non_demo_resident_and_preserves_it(store):
    store.prepare()
    db = Database(store.path)
    db.open()
    real_id = stable_id("resident", "unexpected-real-account")
    db.run_sync(
        lambda conn: conn.execute(
            "INSERT INTO resident (id, display_name, auth_subject, created_at)"
            " VALUES (?, ?, ?, ?)",
            (str(real_id), "Conta real", "real-auth-subject", CLOCK.start.isoformat()),
        )
    )
    db.close()
    with pytest.raises(DemoSafetyError, match="contas/residentes"):
        store.reset()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute(
            "SELECT auth_subject FROM resident WHERE id=?", (str(real_id),)
        ).fetchone() == ("real-auth-subject",)


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
