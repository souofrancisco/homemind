"""Actual SQLite/event-bus integration with simulated readings and no wall clock."""

import asyncio
import sqlite3
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.domain_events import EnergyReadingRecorded
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.energy.consumer import make_step_consumer
from homemind.features.energy.steps import StepTracker
from homemind.features.households.repo import seed_demo


def recorded(seconds, watts, *, household_id=fx.HOUSEHOLD):
    at = fx.T0 + timedelta(seconds=seconds)
    reading = replace(fx.reading(watts, at), id=stable_id("energy-consumer", str(seconds)))
    return EnergyReadingRecorded(
        id=stable_id("energy-consumer", "recorded", str(seconds)),
        ts=at,
        household_id=household_id,
        correlation_id=fx.CORRELATION,
        provenance=reading.provenance,
        data=reading,
    )


def test_consumer_persists_steps_and_sessions_atomically_and_idempotently(tmp_path):
    async def run():
        db = Database(tmp_path / "energy.sqlite3")
        db.open()
        try:
            migrate(db)
            db.run_sync(seed_demo)
            tracker = StepTracker(household_id=fx.HOUSEHOLD)
            bus = EventBus(db)
            bus.subscribe("energy.steps", make_step_consumer(tracker), ["energy.reading_recorded"])
            # Explicit delivery exercises the real bus transaction without sleeps
            # or scheduler timing. The final reading advances the thermostat clock.
            inputs = []
            for seconds, watts in [(0, 0), (30, 2000), (60, 2000), (210, 0), (811, 0)]:
                stored = await bus.publish(recorded(seconds, watts))
                inputs.append(stored)
                assert await bus.deliver("energy.steps", stored)

            events = db.run_sync(load_events)
            generated = [s.event for s in events if s.event.type != "energy.reading_recorded"]
            assert [e.type for e in generated] == [
                "energy.step_detected",
                "energy.consumption_detected",
                "energy.step_detected",
                "energy.consumption_closed",
            ]
            detected, closed = generated[1], generated[3]
            assert closed.data.id == detected.data.id
            assert closed.data.energy_wh == 100
            assert closed.data.ended_at == fx.T0 + timedelta(seconds=210)
            assert all(e.provenance.simulated for e in generated)
            assert [s.seq for s in events] == list(range(1, 10))
            for stored in inputs:
                assert await bus.deliver("energy.steps", stored) is False
            assert db.run_sync(load_events) == events
            processed = db.run_sync(
                lambda c: c.execute(
                    "SELECT count(*) FROM processed_event WHERE consumer = 'energy.steps'"
                ).fetchone()[0]
            )
            assert processed == len(inputs)
        finally:
            db.close()

    asyncio.run(run())


def test_retry_after_outbox_rollback_returns_original_followups(tmp_path):
    async def run():
        db = Database(tmp_path / "retry.sqlite3")
        db.open()
        try:
            migrate(db)
            db.run_sync(seed_demo)
            bus = EventBus(db)
            bus.subscribe(
                "energy.steps",
                make_step_consumer(StepTracker(household_id=fx.HOUSEHOLD)),
                ["energy.reading_recorded"],
            )
            base = await bus.publish(recorded(0, 0))
            await bus.deliver("energy.steps", base)
            up = await bus.publish(recorded(30, 2000))
            # Fail after the step was appended but before the opening event commits.
            db.run_sync(
                lambda c: c.execute(
                    "CREATE TRIGGER reject_consumption BEFORE INSERT ON domain_event "
                    "WHEN NEW.type = 'energy.consumption_detected' "
                    "BEGIN SELECT RAISE(ABORT, 'test rollback'); END"
                )
            )
            with pytest.raises(sqlite3.IntegrityError):
                await bus.deliver("energy.steps", up)
            assert len(db.run_sync(load_events)) == 2  # Only the two source readings.
            db.run_sync(lambda c: c.execute("DROP TRIGGER reject_consumption"))
            assert await bus.deliver("energy.steps", up)
            assert [s.event.type for s in db.run_sync(load_events)][-2:] == [
                "energy.step_detected",
                "energy.consumption_detected",
            ]
            assert await bus.deliver("energy.steps", up) is False
        finally:
            db.close()

    asyncio.run(run())


def test_consumer_does_not_mix_households(tmp_path):
    db = Database(tmp_path / "household.sqlite3")
    db.open()
    try:
        migrate(db)
        db.run_sync(seed_demo)
        tracker = StepTracker(household_id=stable_id("another-household"))
        handler = make_step_consumer(tracker)
        bus = EventBus(db)
        stored = asyncio.run(bus.publish(recorded(0, 2000)))
        assert db.run_sync(lambda conn: handler(conn, stored)) == []
        # The ignored household must not have established a socket baseline.
        assert tracker.ingest(fx.reading(4000, fx.T0 + timedelta(seconds=30))) == []
    finally:
        db.close()
