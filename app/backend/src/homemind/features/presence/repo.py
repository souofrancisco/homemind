"""SQL de presença (dono: presence). Funções síncronas sobre uma `conn` já dentro de uma
transação. Nunca recebem nem devolvem um MAC: só `match_key`."""

import sqlite3
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.presence import PresenceConfirmationRequest, PresenceDevice

MAX_DEVICES_PER_RESIDENT = 5


def is_active_tenant(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, now: datetime
) -> bool:
    """Só moradores (inquilinos) com membership ativa e dentro de datas geram pistas."""
    house = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()
    if house is None:
        return False
    today = now.astimezone(ZoneInfo(house["timezone"])).date().isoformat()
    return (
        conn.execute(
            "SELECT 1 FROM membership WHERE household_id = ? AND resident_id = ?"
            " AND role = 'tenant' AND status = 'active' AND starts_on <= ?"
            " AND (ends_on IS NULL OR ends_on >= ?)",
            (str(household_id), str(resident_id), today, today),
        ).fetchone()
        is not None
    )


# --- telemóveis ------------------------------------------------------------------------------


def _device(row: sqlite3.Row) -> PresenceDevice:
    return PresenceDevice(**{**dict(row), "wifi_opt_in": bool(row["wifi_opt_in"])})


def insert_device(conn: sqlite3.Connection, d: PresenceDevice) -> None:
    conn.execute(
        "INSERT INTO presence_device (id, household_id, resident_id, label, match_key,"
        " wifi_opt_in, consented_at, revoked_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(d.id), str(d.household_id), str(d.resident_id), d.label, d.match_key,
            int(d.wifi_opt_in), _iso(d.consented_at), _iso(d.revoked_at), d.created_at.isoformat(),
        ),
    )  # fmt: skip


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def list_devices(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID
) -> list[PresenceDevice]:
    rows = conn.execute(
        "SELECT * FROM presence_device WHERE household_id = ? AND resident_id = ?"
        " ORDER BY created_at, id",
        (str(household_id), str(resident_id)),
    ).fetchall()
    return [_device(r) for r in rows]


def count_active_devices(conn: sqlite3.Connection, household_id: UUID, resident_id: UUID) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM presence_device WHERE household_id = ? AND resident_id = ?"
        " AND wifi_opt_in = 1",
        (str(household_id), str(resident_id)),
    ).fetchone()[0]


def key_in_use(conn: sqlite3.Connection, household_id: UUID, key: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM presence_device WHERE household_id = ? AND match_key = ?",
            (str(household_id), key),
        ).fetchone()
        is not None
    )


def active_devices(conn: sqlite3.Connection) -> list[PresenceDevice]:
    """Telemóveis com opt-in em vigor (a membership verifica-se em `service`)."""
    rows = conn.execute(
        "SELECT * FROM presence_device WHERE wifi_opt_in = 1 AND revoked_at IS NULL"
    ).fetchall()
    return [_device(r) for r in rows]


def revoke_device(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, device_id: UUID, now: datetime
) -> bool:
    """Revoga um telemóvel do próprio morador e apaga o `match_key` (deixa de ser reconhecível).
    `False` se não existe ou é de outro. Idempotente."""
    row = conn.execute(
        "SELECT consented_at FROM presence_device WHERE id = ? AND household_id = ?"
        " AND resident_id = ?",
        (str(device_id), str(household_id), str(resident_id)),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE presence_device SET wifi_opt_in = 0,"
        " revoked_at = COALESCE(revoked_at, ?), match_key = 'revoked:' || id WHERE id = ?",
        (now.isoformat(), str(device_id)),
    )
    return True


# --- pedidos de confirmação ----------------------------------------------------------------


def insert_confirmation(
    conn: sqlite3.Connection,
    household_id: UUID,
    req: PresenceConfirmationRequest,
    created_at: datetime,
) -> None:
    conn.execute(
        "INSERT INTO presence_confirmation (id, household_id, resident_id, reason, created_at,"
        " expires_at) VALUES (?,?,?,?,?,?)",
        (
            str(req.id), str(household_id), str(req.resident_id), req.reason.value,
            created_at.isoformat(), req.expires_at.isoformat(),
        ),
    )  # fmt: skip


def get_confirmation(conn: sqlite3.Connection, request_id: UUID) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM presence_confirmation WHERE id = ?", (str(request_id),)
    ).fetchone()


def mark_confirmation_answered(conn: sqlite3.Connection, request_id: UUID, at: datetime) -> bool:
    """Compare-and-set: só a primeira resposta conta."""
    cur = conn.execute(
        "UPDATE presence_confirmation SET answered_at = ? WHERE id = ? AND answered_at IS NULL",
        (at.isoformat(), str(request_id)),
    )
    return cur.rowcount == 1
