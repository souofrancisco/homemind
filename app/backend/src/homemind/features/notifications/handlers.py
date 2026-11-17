"""Consumidor do barramento: `billing.confirmation_needed` -> notificação da casa.

Síncrono, sem I/O externo, na transação do efeito (`processed_event`): corre sobre a ligação que o
barramento passa. Idempotente por evento de origem (ids derivados) e devolve os eventos de
seguimento (`notification.created`) para o *outbox*.
"""

import sqlite3
from collections.abc import Callable
from datetime import datetime

from homemind.contracts import domain_events as de
from homemind.contracts.domain_events import StoredEvent
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository

# Nome PERMANENTE do consumidor: é a chave de idempotência em `processed_event`. Renomeá-lo faz
# reprocessar todo o histórico de `billing.confirmation_needed`.
CONFIRMATION_CONSUMER = "notifications.confirmation_needed"
CONFIRMATION_EVENT_TYPES = ("billing.confirmation_needed",)


def make_confirmation_handler(
    clock: Callable[[], datetime],
) -> Callable[[sqlite3.Connection, StoredEvent], list[de.DomainEvent]]:
    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.BillingConfirmationNeeded):  # nunca acontece (filtro de tipos)
            return []
        service = NotificationService(
            SqliteNotificationRepository(conn), SqliteResidentDirectory(conn), clock
        )
        out = service.on_confirmation_needed(
            ev.data,
            source_event_id=ev.id,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler
