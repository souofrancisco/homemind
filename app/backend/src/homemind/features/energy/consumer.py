"""Synchronous event-bus adapter; no I/O, threads or physical actions."""

import sqlite3
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.domain_events import DomainEvent, EnergyReadingRecorded, StoredEvent
from homemind.core.events import Handler
from homemind.features.energy.classifier import classify
from homemind.features.energy.steps import StepTracker, reading_time


def make_step_consumer(tracker: StepTracker, *, catalog: ApplianceCatalog | None = None) -> Handler:
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
            # Catalogue callbacks are valid only inside this handler transaction.
            # Restore constructor hooks even on failure; never retain its connection.
            previous = tracker.classify, tracker.timezone, tracker.ownership_at
            try:
                if catalog is not None:
                    signatures = catalog.signatures_for_household(conn, tracker.household_id)
                    row = conn.execute(
                        "SELECT timezone FROM household WHERE id = ?",
                        (str(tracker.household_id),),
                    ).fetchone()
                    if row is None:
                        raise ValueError("household timezone unavailable")
                    tracker.timezone = ZoneInfo(row[0])
                    tracker.classify = lambda features: classify(features, signatures)
                    tracker.ownership_at = lambda appliance_id, at: catalog.ownership_at(
                        conn, tracker.household_id, appliance_id, at
                    )
                events = tracker.tick(reading_time(reading))
                events.extend(tracker.ingest(reading))
            finally:
                tracker.classify, tracker.timezone, tracker.ownership_at = previous
            results[event.id] = tuple(events)
        return list(results[event.id])

    return handle
