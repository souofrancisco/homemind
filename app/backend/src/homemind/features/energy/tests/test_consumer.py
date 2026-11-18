"""Actual SQLite/event-bus integration with simulated readings and no wall clock."""

import asyncio
import sqlite3
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.billing import AttributionTarget
from homemind.contracts.common import replace, stable_id
from homemind.contracts.devices import ApplianceOwnership, ApplianceScope, SignaturePattern
from homemind.contracts.domain_events import EnergyReadingRecorded
from homemind.contracts.energy import ConsumptionEvent, LocationKind, MatchOutcome
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.billing.attributor import handle as billing_handle
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


class MemoryCatalog:
    """In-memory catalogue port; unused methods fail to detect unexpected coupling."""

    def __init__(self, signatures, ownership):
        self.signatures = signatures
        self.ownership = ownership
        self.reads = []
        self.owner_reads = []

    def signatures_for_household(self, conn, household_id):
        assert conn.in_transaction
        self.reads.append((conn, household_id))
        return self.signatures

    def ownership_at(self, conn, household_id, appliance_id, at):
        assert conn.in_transaction
        self.owner_reads.append((conn, household_id, appliance_id, at))
        return self.ownership.get(appliance_id)

    def register_device(self, conn, device):
        raise AssertionError("unexpected catalogue write")

    def save_appliance_signature(self, conn, household_id, signature):
        raise AssertionError("unexpected catalogue write")

    def meter_at(self, conn, household_id, appliance_id, at):
        raise AssertionError("unexpected meter lookup")

    def meters_for_period(self, conn, household_id, appliance_id, started_at, ended_at):
        raise AssertionError("unexpected meter lookup")

    def context_segments_for_consumption(self, conn, event):
        raise AssertionError("unexpected context lookup")

    def context_for_consumption(self, conn, event):
        raise AssertionError("unexpected context lookup")

    def appliances_for_household(self, conn, household_id, at):  # ENERGY-01 (contrato)
        raise AssertionError("unexpected appliance listing")


@pytest.mark.parametrize(
    "duration,personal,ambiguous", [(180, False, False), (7200, True, False), (180, False, True)]
)
def test_catalogue_publishes_provisional_and_final_match_in_same_consumption(
    duration, personal, ambiguous
):
    async def run():
        kettle = stable_id("consumer", "kettle")
        heater_signature = replace(
            fx.heater_signature(),
            duration_typical_s=7200,
            pattern=SignaturePattern.continuous,
            typical_hours=[8],
        )
        kettle_signature = replace(
            heater_signature,
            id=stable_id("consumer", "kettle-signature"),
            appliance_id=kettle,
            duration_typical_s=180,
            pattern=SignaturePattern.short,
        )
        if ambiguous:
            heater_signature = replace(kettle_signature, appliance_id=fx.HEATER)
        catalog = MemoryCatalog(
            {kettle: [kettle_signature], fx.HEATER: [heater_signature]},
            {
                kettle: ApplianceOwnership(scope=ApplianceScope.common),
                fx.HEATER: fx.heater().ownership,
            },
        )
        assert isinstance(catalog, ApplianceCatalog)
        db = Database(":memory:")
        db.open()
        try:
            migrate(db)
            db.run_sync(seed_demo)
            db.run_sync(
                lambda c: c.execute(
                    "UPDATE household SET timezone = 'Pacific/Auckland' WHERE id = ?",
                    (str(fx.HOUSEHOLD),),
                )
            )
            tracker = StepTracker(household_id=fx.HOUSEHOLD)
            handler = make_step_consumer(tracker, catalog=catalog)
            bus = EventBus(db)
            bus.subscribe("energy.steps", handler, ["energy.reading_recorded"])
            inputs = []
            for seconds, watts in [(0, 0), (30, 2000), (30 + duration, 0), (631 + duration, 0)]:
                stored = await bus.publish(recorded(seconds, watts))
                inputs.append(stored)
                await bus.deliver("energy.steps", stored)
            generated = [
                s
                for s in db.run_sync(load_events)
                if s.event.type in ("energy.consumption_detected", "energy.consumption_closed")
            ]
            assert len(generated) == 2
            detected, closed = (s.event.data for s in generated)
            assert detected.id == closed.id
            assert detected.match.outcome is MatchOutcome.ambiguous
            assert detected.match.appliance_id is detected.match.confidence is None
            assert detected.appliance_owner_resident_id is None
            assert len(detected.match.candidates) == 2
            assert all(c.confidence == 1 for c in detected.match.candidates)  # local 08:00
            assert closed.location is LocationKind.unknown
            assert closed.room_id is None
            assert closed.energy_wh == round(2000 * duration / 3600)
            assert ConsumptionEvent.model_validate_json(closed.model_dump_json()) == closed
            if ambiguous:
                assert closed.match.outcome is MatchOutcome.ambiguous
                assert closed.match.appliance_id is closed.match.confidence is None
                assert closed.appliance_owner_resident_id is None
                assert catalog.owner_reads == []
                billing = db.run_sync(lambda c: billing_handle(c, generated[-1]))
                assert len(billing) == 1
                assert billing[0].data.target_type is AttributionTarget.common
                assert billing[0].data.target_resident_id is None
            else:
                assert closed.match.appliance_id == (fx.HEATER if personal else kettle)
                assert closed.match.confidence == 1
                assert closed.appliance_owner_resident_id == (fx.BRUNO if personal else None)
                assert len(catalog.owner_reads) == 1
                conn, household, appliance, at = catalog.owner_reads[0]
                assert household == fx.HOUSEHOLD and appliance == closed.match.appliance_id
                assert at == closed.started_at
                assert conn is catalog.reads[-1][0]
            assert len(catalog.reads) == len(inputs)
            assert all(household == fx.HOUSEHOLD for _, household in catalog.reads)
            # Retry returns cached follow-ups without a new catalogue read.
            cached = db.run_sync(lambda c: handler(c, inputs[-1]))
            assert cached == [generated[-1].event]
            assert len(catalog.reads) == len(inputs)
            assert tracker.classify is tracker.ownership_at is None
        finally:
            db.close()

    asyncio.run(run())
