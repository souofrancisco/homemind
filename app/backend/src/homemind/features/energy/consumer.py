"""Synchronous event-bus adapter; no I/O, threads or physical actions."""

import sqlite3
from uuid import UUID

from homemind.contracts.domain_events import DomainEvent, EnergyReadingRecorded, StoredEvent
from homemind.core.events import Handler
from homemind.features.energy.steps import StepTracker, reading_time


def make_step_consumer(tracker: StepTracker) -> Handler:
    # The bus can roll back after our in-memory tracker has advanced. Re-delivery
    # must return the original follow-ups, including after intervening readings.
    # This cache, like the tracker itself, lasts only for this process lifetime.
    results: dict[UUID, tuple[DomainEvent, ...]] = {}

    def handle(conn: sqlite3.Connection, stored: StoredEvent) -> list[DomainEvent]:
        event = stored.event
        if not isinstance(event, EnergyReadingRecorded):
            return []
        if event.household_id != tracker.household_id:
            return []
        if event.id not in results:
            reading = event.data
            events = tracker.tick(reading_time(reading))
            events.extend(tracker.ingest(reading))
            results[event.id] = tuple(events)
        return list(results[event.id])

    return handle
