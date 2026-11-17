"""Liga o `SafetyEngine` ao barramento. Sem migrações: o estado reconstrói-se do registo de
eventos (já persistente e auditado) e os alertas são eventos `safety.alert_raised`."""

from __future__ import annotations

import sqlite3

from homemind.contracts.domain_events import StoredEvent
from homemind.core.events import EventBus, load_events
from homemind.features.safety.engine import HeatingResolver, SafetyEngine, no_heating_known

CONSUMER = "safety"
INPUT_TYPES = (
    "sensor.reading_recorded",
    "energy.consumption_detected",
    "energy.consumption_closed",
)


class SafetyService:
    def __init__(
        self,
        is_heating: HeatingResolver = no_heating_known,
    ) -> None:
        self.engine = SafetyEngine(is_heating)

    def handle(self, _conn: sqlite3.Connection, stored: StoredEvent):
        return self.engine.on_event(stored.event)

    def restore(self, conn: sqlite3.Connection) -> int:
        """Refaz o estado a partir dos eventos já entregues a este consumidor (os alertas
        que produziriam já estão no registo, por isso a saída descarta-se)."""
        done = {
            r[0]
            for r in conn.execute(
                "SELECT event_id FROM processed_event WHERE consumer = ?", (CONSUMER,)
            )
        }
        n = 0
        for s in load_events(conn, types=INPUT_TYPES):
            if str(s.event.id) in done:
                self.engine.on_event(s.event)
                n += 1
        return n

    def attach(self, bus: EventBus) -> None:
        bus.db.run_sync(self.restore)
        bus.subscribe(CONSUMER, self.handle, types=INPUT_TYPES)
