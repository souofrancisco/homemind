"""SQL de presença (dono: presence). Funções síncronas sobre uma `conn` já dentro de uma
transação. Nunca recebem nem devolvem um MAC: só `match_key`."""

import json
import sqlite3
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.common import Provenance
from homemind.contracts.presence import (
    DoorCrossed,
    PersonPresence,
    PresenceConfirmationRequest,
    PresenceDevice,
    PresenceEvent,
    PresenceSource,
    PresenceState,
    UncertainReason,
)

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


def has_presence_opt_in(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, now: datetime
) -> bool:
    """`Membership.presence_opt_in` em vigor (além de membership ativa de inquilino)."""
    return (
        is_active_tenant(conn, household_id, resident_id, now)
        and conn.execute(
            "SELECT 1 FROM membership WHERE household_id = ? AND resident_id = ?"
            " AND status = 'active' AND presence_opt_in = 1",
            (str(household_id), str(resident_id)),
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


# --- pistas e passagens (lidas do registo imutável de eventos) --------------------------------


def load_cues(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, since: datetime
) -> list[PresenceEvent]:
    rows = conn.execute(
        "SELECT payload_json FROM domain_event WHERE type = 'presence.cue_recorded'"
        " AND household_id = ? AND json_extract(payload_json, '$.resident_id') = ?"
        " AND ts >= ? ORDER BY seq",
        (str(household_id), str(resident_id), since.isoformat()),
    ).fetchall()
    return [PresenceEvent.model_validate_json(r[0]) for r in rows]


def load_doors(conn: sqlite3.Connection, household_id: UUID, since: datetime) -> list[DoorCrossed]:
    rows = conn.execute(
        "SELECT payload_json FROM domain_event WHERE type = 'presence.door_crossed'"
        " AND household_id = ? AND ts >= ? ORDER BY seq",
        (str(household_id), since.isoformat()),
    ).fetchall()
    return [DoorCrossed.model_validate_json(r[0]) for r in rows]


def cue_exists(conn: sqlite3.Connection, event_id: UUID) -> bool:
    return (
        conn.execute("SELECT 1 FROM domain_event WHERE id = ?", (str(event_id),)).fetchone()
        is not None
    )


# --- moradores -------------------------------------------------------------------------------


def active_tenants(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> list[UUID]:
    house = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()
    if house is None:
        return []
    today = now.astimezone(ZoneInfo(house["timezone"])).date().isoformat()
    rows = conn.execute(
        "SELECT resident_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status = 'active' AND starts_on <= ? AND (ends_on IS NULL OR ends_on >= ?)"
        " ORDER BY starts_on, resident_id",
        (str(household_id), today, today),
    ).fetchall()
    return [UUID(r[0]) for r in rows]


def membership_start(conn: sqlite3.Connection, household_id: UUID, resident_id: UUID) -> datetime:
    row = conn.execute(
        "SELECT starts_on FROM membership WHERE household_id = ? AND resident_id = ?"
        " AND status = 'active'",
        (str(household_id), str(resident_id)),
    ).fetchone()
    day = datetime.fromisoformat(row[0]) if row else datetime.min
    return day.replace(tzinfo=UTC)


# --- estado fundido --------------------------------------------------------------------------


def get_state(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID
) -> PersonPresence | None:
    r = conn.execute(
        "SELECT * FROM presence_state WHERE household_id = ? AND resident_id = ?",
        (str(household_id), str(resident_id)),
    ).fetchone()
    if r is None:
        return None
    return PersonPresence(
        resident_id=UUID(r["resident_id"]),
        state=PresenceState(r["state"]),
        since=datetime.fromisoformat(r["since"]),
        confidence=r["confidence"],
        provenance=Provenance(origin=r["origin"], kind=r["kind"]),
        sources=[PresenceSource(x) for x in json.loads(r["sources_json"])],
        reason=UncertainReason(r["reason"]) if r["reason"] else None,
    )


def upsert_state(
    conn: sqlite3.Connection, household_id: UUID, p: PersonPresence, now: datetime
) -> None:
    conn.execute(
        "INSERT INTO presence_state (household_id, resident_id, state, since, confidence, origin,"
        " kind, sources_json, reason, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT (household_id, resident_id) DO UPDATE SET state = excluded.state,"
        " since = excluded.since, confidence = excluded.confidence, origin = excluded.origin,"
        " kind = excluded.kind, sources_json = excluded.sources_json, reason = excluded.reason,"
        " updated_at = excluded.updated_at",
        (
            str(household_id), str(p.resident_id), p.state.value, p.since.isoformat(),
            p.confidence, p.provenance.origin.value, p.provenance.kind.value,
            json.dumps([x.value for x in p.sources]),
            p.reason.value if p.reason else None, now.isoformat(),
        ),
    )  # fmt: skip


def others_in(conn: sqlite3.Connection, household_id: UUID, resident_id: UUID) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM presence_state WHERE household_id = ? AND resident_id != ?"
        " AND state = 'in'",
        (str(household_id), str(resident_id)),
    ).fetchone()[0]


def tracked_residents(conn: sqlite3.Connection) -> list[tuple[UUID, UUID]]:
    rows = conn.execute("SELECT household_id, resident_id FROM presence_state").fetchall()
    return [(UUID(r[0]), UUID(r[1])) for r in rows]


def last_confirmation_at(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID
) -> datetime | None:
    r = conn.execute(
        "SELECT MAX(created_at) FROM presence_confirmation WHERE household_id = ?"
        " AND resident_id = ?",
        (str(household_id), str(resident_id)),
    ).fetchone()
    return datetime.fromisoformat(r[0]) if r and r[0] else None


# --- estado agregado da casa (PRES-05/06) ----------------------------------------------------


def get_house_state(conn: sqlite3.Connection, household_id: UUID) -> tuple[str, datetime] | None:
    r = conn.execute(
        "SELECT state, since FROM presence_house_state WHERE household_id = ?",
        (str(household_id),),
    ).fetchone()
    return None if r is None else (r[0], datetime.fromisoformat(r[1]))


def set_house_state(
    conn: sqlite3.Connection, household_id: UUID, state: str, now: datetime
) -> None:
    conn.execute(
        "INSERT INTO presence_house_state (household_id, state, since) VALUES (?,?,?)"
        " ON CONFLICT (household_id) DO UPDATE SET state = excluded.state,"
        " since = excluded.since",
        (str(household_id), state, now.isoformat()),
    )


def houses_with_house_state(conn: sqlite3.Connection) -> list[UUID]:
    return [UUID(r[0]) for r in conn.execute("SELECT household_id FROM presence_house_state")]
