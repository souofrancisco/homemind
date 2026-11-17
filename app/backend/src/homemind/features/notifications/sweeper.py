"""Varrimento de expiração: passa a `expired` as notificações abertas cujo `expires_at` passou.

O estado expirado já se deduz do tempo na leitura (`Notification.is_expired`); o varrimento só
o grava, para o histórico e para os filtros por estado. Não emite eventos (a proposta
`notification.expired` está em revisão): a P4 divide por todos pelo seu próprio prazo.
"""

import asyncio
import logging
import sqlite3

from homemind.core.db import Database
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.ports import Clock
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository

log = logging.getLogger(__name__)


def sweep_once(conn: sqlite3.Connection, clock: Clock) -> int:
    """Um varrimento, na transação de `conn`; devolve quantas notificações expirou."""
    service = NotificationService(
        SqliteNotificationRepository(conn), SqliteResidentDirectory(conn), clock
    )
    return len(service.expire_due())


async def expiry_loop(db: Database, clock: Clock, interval_s: float) -> None:
    """Corre até ser cancelada. Uma falha num varrimento só se regista (o tipo) e o seguinte
    tenta outra vez; o primeiro varrimento é depois de `interval_s`."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            expired = await db.run(lambda conn: sweep_once(conn, clock))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - só o tipo vai para o log
            log.warning("varrimento de expiração falhou (%s)", type(e).__name__)
            continue
        if expired:
            log.info("notificações expiradas: %d", expired)
