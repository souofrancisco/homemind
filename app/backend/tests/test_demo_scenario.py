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
from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import CostEstimate, MatchOutcome, ReadingStatus
from homemind.contracts.notification import ConfirmationVerdict, Notification
from homemind.core.db import MIGRATIONS_DIR, Database
from homemind.core.events import EventBus, append_event, load_events
from homemind.demo.cli import FILE_NAME, DemoSafetyError, DemoStore
from homemind.demo.scenario import CLOCK, POWER_PROFILE, events, power_samples, references
from homemind.features.billing import attributor
from homemind.features.energy.consumer import make_step_consumer
from homemind.features.energy.steps import StepTracker
from homemind.features.households.repo import insert_household
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.handlers import (
    ATTRIBUTION_CONSUMER,
    ATTRIBUTION_EVENT_TYPES,
    CONFIRMATION_CONSUMER,
    CONFIRMATION_EVENT_TYPES,
    make_attribution_handler,
    make_confirmation_handler,
)
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository
from homemind.features.presence.service import PresenceService


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


def test_replay_contains_energy_and_presence_inputs_not_consumer_outputs():
    types = {event.type for event in events()}
    assert "energy.reading_recorded" in types
    assert "presence.door_crossed" in types
    assert not types.intersection(
        {
            "energy.step_detected",
            "energy.consumption_detected",
            "energy.consumption_closed",
            "billing.confirmation_needed",
            "billing.attribution_changed",
            "notification.created",
            "notification.responded",
        }
    )


def test_presence_is_anonymous_and_no_consumer_output_is_fabricated():
    timeline = events()
    doors = [e for e in timeline if e.type == "presence.door_crossed"]
    assert len(doors) == 2
    assert [e.data.direction.value for e in doors] == ["in", "out"]
    assert all("resident_id" not in e.data.model_dump() for e in doors)
    assert not any(e.type == "presence.changed" for e in timeline)
    assert not any(e.type == "billing.confirmation_needed" for e in timeline)
    assert not any(e.type in {"notification.created", "notification.responded"} for e in timeline)
    assert not any(e.type == "billing.attribution_changed" for e in timeline)


def test_real_presence_consumer_keeps_demo_door_crossing_anonymous(store):
    store.prepare()
    db = Database(store.path)
    db.open()
    try:
        bus = EventBus(db)
        service = PresenceService(
            db,
            bus,
            salt="",
            clock=lambda: CLOCK.at(160),
            wifi_enabled=False,
        )
        crossed = next(
            item for item in db.run_sync(load_events) if item.event.type == "presence.door_crossed"
        )
        assert db.run_sync(lambda conn: service.on_presence_input(conn, crossed)) == []
        assert (
            db.run_sync(
                lambda conn: conn.execute("SELECT count(*) FROM presence_state").fetchone()[0]
            )
            == 0
        )
        assert "resident_id" not in crossed.event.data.model_dump()
    finally:
        db.close()


def test_energy_inputs_have_no_nilm_labels_or_resident_identity():
    readings = [e.data for e in events() if e.type == "energy.reading_recorded"]
    assert readings
    assert all("match" not in reading.model_dump() for reading in readings)
    assert all("resident_id" not in reading.model_dump() for reading in readings)


def test_real_energy_consumer_processes_simulated_demo_readings(store, monkeypatch):
    monkeypatch.setattr(attributor, "ignore_wh_month", lambda: 0)  # a demo mostra a pergunta
    store.prepare()
    db = Database(store.path)
    db.open()
    try:
        bus = EventBus(db)
        bus.subscribe(
            "energy.steps",
            make_step_consumer(StepTracker(household_id=fx.HOUSEHOLD)),
            ["energy.reading_recorded"],
        )
        bus.subscribe(attributor.CONSUMER, attributor.handle, attributor.EVENT_TYPES)
        inputs = db.run_sync(lambda conn: load_events(conn, types=["energy.reading_recorded"]))
        assert len(inputs) == len(POWER_PROFILE) + 1  # readings plus explicit missing sample
        assert all(asyncio.run(bus.deliver("energy.steps", stored)) for stored in inputs)

        all_events = db.run_sync(load_events)
        outputs = [
            item.event
            for item in all_events
            if item.event.type.startswith("energy.")
            and item.event.type != "energy.reading_recorded"
        ]
        assert outputs
        assert {item.type for item in outputs} <= {
            "energy.step_detected",
            "energy.consumption_detected",
            "energy.consumption_closed",
        }
        assert all(item.provenance.simulated for item in outputs)
        consumption = [
            item.data
            for item in outputs
            if item.type in {"energy.consumption_detected", "energy.consumption_closed"}
        ]
        assert consumption
        assert all(item.match.outcome is MatchOutcome.unknown for item in consumption)
        assert all(item.energy_wh is None or item.energy_wh >= 0 for item in consumption)
        assert all(item.cost_estimate is None for item in consumption)

        generated_consumptions = db.run_sync(
            lambda conn: load_events(
                conn,
                types=["energy.consumption_detected", "energy.consumption_closed"],
            )
        )
        assert generated_consumptions
        assert all(
            asyncio.run(bus.deliver(attributor.CONSUMER, stored))
            for stored in generated_consumptions
        )
        active = db.run_sync(
            lambda conn: conn.execute(
                "SELECT json FROM billing_attribution WHERE status = 'active'"
            ).fetchall()
        )
        asked = db.run_sync(
            lambda conn: conn.execute(
                "SELECT count(*) FROM billing_confirmation WHERE status = 'pending'"
            ).fetchone()[0]
        )
        # BILL-02: sem custo de energy, billing estima-o pelo preço de referência; os consumos
        # que valem a pena (≥ 0,50 €) ficam à espera da pergunta, os outros decidem-se já.
        closed = {item.id for item in consumption if item.status.value == "closed"}
        assert len(active) + asked == len(closed)
        assert asked >= 1
    finally:
        db.close()


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


def test_prepare_refuses_old_or_extra_scenario_events_without_mutating_db(store):
    store.prepare()
    legacy_step = de.EnergyStepDetected(
        ts=CLOCK.at(1),
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED,
        data=replace(fx.step(), id=stable_id("previous-demo-step")),
    )
    db = Database(store.path)
    db.open()
    try:
        db.run_sync(lambda conn: append_event(conn, legacy_step))
        before = db.run_sync(load_events)
    finally:
        db.close()

    with pytest.raises(DemoSafetyError, match="demo-reset"):
        store.prepare()

    db = Database(store.path)
    db.open()
    try:
        assert db.run_sync(load_events) == before
    finally:
        db.close()


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
    assert {"0101_billing_attributions.sql", "0102_billing_allocations.sql"} <= applied
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


def test_real_p4_p3_consumers_and_d32_votes_use_isolated_demo_db(store):
    store.prepare()
    db = Database(store.path)
    db.open()
    try:
        consumption = replace(
            fx.consumption(closed=True),
            energy_wh=5000,
            cost_estimate=CostEstimate(cents=80, price_millicents_per_kwh=16_000),
        )
        source = de.EnergyConsumptionClosed(
            ts=CLOCK.at(131),
            household_id=fx.HOUSEHOLD,
            provenance=consumption.provenance,
            data=consumption,
        )

        bus = EventBus(db)
        bus.subscribe(attributor.CONSUMER, attributor.handle, attributor.EVENT_TYPES)
        bus.subscribe(
            CONFIRMATION_CONSUMER,
            make_confirmation_handler(lambda: CLOCK.at(132)),
            CONFIRMATION_EVENT_TYPES,
        )
        bus.subscribe(
            ATTRIBUTION_CONSUMER,
            make_attribution_handler(lambda: CLOCK.at(134)),
            ATTRIBUTION_EVENT_TYPES,
        )
        stored_source = db.run_sync(lambda conn: append_event(conn, source))
        assert asyncio.run(bus.deliver(attributor.CONSUMER, stored_source))
        assert not asyncio.run(bus.deliver(attributor.CONSUMER, stored_source))
        confirmation = next(
            row
            for row in db.run_sync(load_events)
            if row.event.type == "billing.confirmation_needed"
        )
        assert isinstance(confirmation.event, de.BillingConfirmationNeeded)
        assert asyncio.run(bus.deliver(CONFIRMATION_CONSUMER, confirmation))
        assert not asyncio.run(bus.deliver(CONFIRMATION_CONSUMER, confirmation))
        assert (
            db.run_sync(
                lambda conn: conn.execute(
                    "SELECT count(*) FROM domain_event WHERE type = 'notification.created'"
                ).fetchone()[0]
            )
            == 1
        )
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

        responded = db.run_sync(
            lambda conn: load_events(conn, types=["notification.responded"])[-1]
        )

        assert asyncio.run(bus.deliver(attributor.CONSUMER, responded))
        assert not asyncio.run(bus.deliver(attributor.CONSUMER, responded))
        attributed = next(
            row
            for row in db.run_sync(load_events)
            if row.event.type == "billing.attribution_changed"
        )
        assert isinstance(attributed.event, de.BillingAttributionChanged)
        assert attributed.event.data.target_resident_id == fx.BRUNO
        assert asyncio.run(bus.deliver(ATTRIBUTION_CONSUMER, attributed))
        assert not asyncio.run(bus.deliver(ATTRIBUTION_CONSUMER, attributed))
        saved = db.run_sync(lambda conn: attributor.active_attribution(conn, consumption.id))
        assert saved == attributed.event.data
        assert (
            db.run_sync(
                lambda conn: conn.execute("SELECT count(*) FROM notification").fetchone()[0]
            )
            == 2
        )
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


@pytest.mark.parametrize("action", ("prepare", "reset"))
def test_demo_operations_refuse_sidecars_even_when_database_is_missing(store, action):
    store.root.mkdir()
    wal = Path(f"{store.path}-wal")
    wal.write_bytes(b"unowned wal data")
    with pytest.raises(DemoSafetyError, match="WAL/SHM"):
        getattr(store, action)()
    assert wal.read_bytes() == b"unowned wal data"
    assert not store.path.exists()


def test_demo_reset_refuses_live_sidecars_without_replacing_database(store):
    store.prepare()
    original = store.path.read_bytes()
    wal = Path(f"{store.path}-wal")
    shm = Path(f"{store.path}-shm")
    wal.write_bytes(b"unowned wal data")
    shm.write_bytes(b"unowned shm data")
    with pytest.raises(DemoSafetyError, match="WAL/SHM"):
        store.reset()
    assert store.path.read_bytes() == original
    assert wal.read_bytes() == b"unowned wal data"
    assert shm.read_bytes() == b"unowned shm data"


def test_demo_reset_refuses_symlinked_parent_path(store, tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    store_through_link = DemoStore(linked / "private")
    with pytest.raises(DemoSafetyError, match="symlink"):
        store_through_link.reset()
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
