"""Ajudantes dos testes dos consumidores: entrega de eventos ao barramento real (SQLite em
memória) e leitura do resultado. Sem rede nem relógio real."""

import asyncio
from datetime import datetime, timedelta

from homemind.contracts import fixtures as fx
from homemind.contracts.notification import Notification
from homemind.core.events import EventBus, load_events
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.handlers import CONSUMERS
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository

# 18:30 UTC: depois da membership (1/9) e antes de qualquer `expires_at` das fixtures (T0 = 19:00).
NOW = fx.T0 - timedelta(minutes=30)


def deliver(db, consumer: str, *events, now: datetime = NOW, twice: bool = False) -> list[bool]:
    """Publica cada evento e entrega-o ao consumidor (duas vezes com `twice`)."""
    name, make_handler, types = next(c for c in CONSUMERS if c[0] == consumer)
    bus = EventBus(db)
    bus.subscribe(name, make_handler(lambda: now), types)

    async def go() -> list[bool]:
        results = []
        for ev in events:
            stored = await bus.publish(ev)
            results.append(await bus.deliver(name, stored))
            if twice:
                results.append(await bus.deliver(name, stored))
        return results

    return asyncio.run(go())


def all_notifications(db, household=fx.HOUSEHOLD) -> list[Notification]:
    return db.run_sync(lambda c: SqliteNotificationRepository(c).list_household(household))


def created_events(db):
    return db.run_sync(lambda c: load_events(c, types=["notification.created"]))


def visible_to(db, resident, now: datetime = NOW, household=fx.HOUSEHOLD):
    """Vistas que `resident` recebe em `GET .../notifications`."""
    return db.run_sync(
        lambda c: NotificationService(
            SqliteNotificationRepository(c), SqliteResidentDirectory(c), lambda: now
        ).list_for(household, resident)
    )


def end_membership(db, resident, household=fx.HOUSEHOLD) -> None:
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-01'"
            " WHERE household_id = ? AND resident_id = ?",
            (str(household), str(resident)),
        )
    )
