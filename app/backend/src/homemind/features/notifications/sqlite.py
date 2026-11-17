"""Persistência SQLite das notificações (migração `core/migrations/0300_notifications_core.sql`).

Funções e classes SÍNCRONAS sobre uma `sqlite3.Connection` já dentro de uma transação
(`db.run`/`db.run_sync`, ou o handler do barramento): nunca abrem nem fecham transações.
A coluna `json` é a `Notification` validada; as colunas escalares servem para filtrar e para o
índice único de deduplicação. `compare_and_set` é
`UPDATE ... WHERE id = ? AND status = ? AND json_array_length(json, '$.responses') = ?` com 1
linha afetada: o par (estado, n.º de votos) só avança, por isso votos simultâneos nunca se
perdem nem se duplicam (quem leu antes perde e relê).
"""

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from homemind.contracts.notification import (
    Notification,
    NotificationKind,
    NotificationPreferences,
    NotificationRef,
    NotificationStatus,
)

_OPEN = (NotificationStatus.unread.value, NotificationStatus.read.value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _notification(row: sqlite3.Row) -> Notification:
    return Notification.model_validate_json(row["json"])


class SqliteNotificationRepository:
    """Cumpre `NotificationRepository` (ver `repository.py`) sobre a ligação da transação."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, notification_id: UUID) -> Notification | None:
        row = self._conn.execute(
            "SELECT json FROM notification WHERE id = ?", (str(notification_id),)
        ).fetchone()
        return _notification(row) if row else None

    def insert(self, n: Notification) -> bool:
        cur = self._conn.execute(
            "INSERT INTO notification (id, household_id, scope, recipient_resident_id, kind,"
            " status, ref_type, ref_id, expires_at, created_at, origin, json, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING",
            (
                str(n.id),
                str(n.household_id),
                n.scope.value,
                str(n.recipient_resident_id) if n.recipient_resident_id else None,
                n.kind.value,
                n.status.value,
                n.ref.type.value if n.ref else None,
                str(n.ref.id) if n.ref else None,
                n.expires_at.isoformat() if n.expires_at else None,
                n.created_at.isoformat(),
                n.origin.value,
                n.model_dump_json(),
                _now(),
            ),
        )
        return cur.rowcount == 1

    def find_open(
        self,
        *,
        household_id: UUID,
        kind: NotificationKind,
        ref: NotificationRef | None,
        recipient_resident_id: UUID | None,
    ) -> Notification | None:
        row = self._conn.execute(
            "SELECT json FROM notification WHERE household_id = ? AND kind = ?"
            " AND ref_type IS ? AND ref_id IS ? AND recipient_resident_id IS ?"
            " AND status IN (?, ?) ORDER BY created_at DESC, id DESC LIMIT 1",
            (
                str(household_id),
                kind.value,
                ref.type.value if ref else None,
                str(ref.id) if ref else None,
                str(recipient_resident_id) if recipient_resident_id else None,
                *_OPEN,
            ),
        ).fetchone()
        return _notification(row) if row else None

    def find_by_ref(
        self,
        *,
        household_id: UUID,
        ref: NotificationRef,
        kind: NotificationKind | None = None,
        open_only: bool = False,
    ) -> list[Notification]:
        sql = "SELECT json FROM notification WHERE household_id = ? AND ref_type = ? AND ref_id = ?"
        args: list[str] = [str(household_id), ref.type.value, str(ref.id)]
        if kind is not None:
            sql += " AND kind = ?"
            args.append(kind.value)
        if open_only:
            sql += " AND status IN (?, ?)"
            args += _OPEN
        rows = self._conn.execute(sql + " ORDER BY created_at, id", args).fetchall()
        return [_notification(r) for r in rows]

    def compare_and_set(self, new: Notification, *, expected: Notification) -> bool:
        cur = self._conn.execute(
            "UPDATE notification SET status = ?, json = ?, updated_at = ?"
            " WHERE id = ? AND status = ? AND json_array_length(json, '$.responses') = ?",
            (
                new.status.value,
                new.model_dump_json(),
                _now(),
                str(new.id),
                expected.status.value,
                len(expected.responses),
            ),
        )
        return cur.rowcount == 1

    def list_household(self, household_id: UUID) -> list[Notification]:
        rows = self._conn.execute(
            "SELECT json FROM notification WHERE household_id = ? ORDER BY created_at, id",
            (str(household_id),),
        ).fetchall()
        return [_notification(r) for r in rows]

    def open_due(self, now: datetime) -> list[Notification]:
        rows = self._conn.execute(
            "SELECT json FROM notification WHERE status IN (?, ?) AND expires_at IS NOT NULL",
            _OPEN,
        ).fetchall()
        # A comparação de datas faz-se em Python (texto ISO com formatos variáveis).
        return [n for n in map(_notification, rows) if n.is_expired(now)]

    def mark_read(self, notification_id: UUID, resident_id: UUID, at: datetime) -> bool:
        """Recibo de leitura por residente; `True` se foi criado agora (a notificação tem de
        existir)."""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO notification_read (notification_id, resident_id, read_at)"
            " SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM notification WHERE id = ?)",
            (str(notification_id), str(resident_id), at.isoformat(), str(notification_id)),
        )
        return cur.rowcount == 1

    def read_at(self, notification_id: UUID, resident_id: UUID) -> datetime | None:
        row = self._conn.execute(
            "SELECT read_at FROM notification_read WHERE notification_id = ? AND resident_id = ?",
            (str(notification_id), str(resident_id)),
        ).fetchone()
        return datetime.fromisoformat(row["read_at"]) if row else None


def load_preferences(
    conn: sqlite3.Connection, resident_id: UUID, household_id: UUID
) -> NotificationPreferences | None:
    """Preferências do residente NESSA casa (as horas de silêncio são locais à casa)."""
    row = conn.execute(
        "SELECT json FROM notification_preferences WHERE resident_id = ? AND household_id = ?",
        (str(resident_id), str(household_id)),
    ).fetchone()
    return NotificationPreferences.model_validate_json(row["json"]) if row else None


def save_preferences(
    conn: sqlite3.Connection, household_id: UUID, prefs: NotificationPreferences
) -> None:
    conn.execute(
        "INSERT INTO notification_preferences (resident_id, household_id, json, updated_at)"
        " VALUES (?,?,?,?) ON CONFLICT (resident_id, household_id) DO UPDATE SET"
        " json = excluded.json, updated_at = excluded.updated_at",
        (str(prefs.resident_id), str(household_id), prefs.model_dump_json(), _now()),
    )
