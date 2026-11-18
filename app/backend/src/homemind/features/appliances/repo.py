"""SQLite catalogue. Transactions are supplied by core.db; no MCP or billing logic."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.appliance_catalog import (
    ApplianceCatalog,
    ApplianceContextSegment,
    ApplianceSnapshot,
    DeviceLocation,
    MeterContextSegment,
)
from homemind.contracts.common import new_id
from homemind.contracts.devices import (
    ApplianceOwnership,
    ApplianceScope,
    ApplianceSignature,
    Device,
    DeviceRole,
    DeviceView,
)
from homemind.contracts.energy import ConsumptionEvent
from homemind.contracts.household import RoomKind
from homemind.core.access import Grant, HouseholdAccess
from homemind.features.appliances.schemas import (
    ApplianceCreate,
    ApplianceDiagnosticView,
    ApplianceHistoryView,
    AppliancePatch,
    ApplianceView,
    DeviceCreateDemo,
)


class CatalogError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def timestamp(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("o relógio do catálogo precisa de UTC com timezone")
    return now.astimezone(UTC).isoformat(timespec="microseconds")


def _not_found() -> CatalogError:
    return CatalogError(404, "appliance_not_found", "Aparelho não encontrado")


def _invalid(message: str) -> CatalogError:
    return CatalogError(422, "invalid_request", message)


def _active_tenant(conn: sqlite3.Connection, house: UUID, resident: UUID, at: datetime) -> bool:
    row = conn.execute("SELECT timezone FROM household WHERE id = ?", (str(house),)).fetchone()
    if row is None:
        return False
    day = at.astimezone(ZoneInfo(row["timezone"])).date().isoformat()
    return (
        conn.execute(
            "SELECT 1 FROM membership WHERE household_id = ? AND resident_id = ?"
            " AND role = 'tenant' AND status = 'active' AND starts_on <= ?"
            " AND (ends_on IS NULL OR ends_on >= ?) LIMIT 1",
            (str(house), str(resident), day, day),
        ).fetchone()
        is not None
    )


def _check_room(conn: sqlite3.Connection, house: UUID, room: UUID | None) -> None:
    if (
        room is not None
        and conn.execute(
            "SELECT 1 FROM room WHERE household_id = ? AND id = ?",
            (str(house), str(room)),
        ).fetchone()
        is None
    ):
        raise _invalid("Divisão não pertence à casa")


def _check_owner(
    conn: sqlite3.Connection,
    house: UUID,
    scope: ApplianceScope,
    owner: UUID | None,
    at: datetime,
) -> None:
    if scope is ApplianceScope.common:
        if owner is not None:
            raise _invalid("Aparelho comum não tem proprietário")
    elif owner is None or not _active_tenant(conn, house, owner, at):
        raise _invalid("Proprietário deve ser um inquilino ativo desta casa")


def _current(conn: sqlite3.Connection, house: UUID, appliance: UUID) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT a.*, s.scope, s.owner_resident_id, s.home_room_id, s.valid_from"
        " FROM appliance a JOIN appliance_state s ON s.id = ("
        " SELECT latest.id FROM appliance_state latest WHERE latest.appliance_id = a.id"
        " ORDER BY latest.valid_from DESC,latest.id DESC LIMIT 1)"
        " WHERE a.id = ? AND a.household_id = ?",
        (str(appliance), str(house)),
    ).fetchone()


def _can_read(row: sqlite3.Row, access: HouseholdAccess) -> bool:
    return (
        access.grant is Grant.diagnostic
        or row["scope"] == "common"
        or row["owner_resident_id"] == str(access.resident_id)
    )


def _can_write(row: sqlite3.Row, access: HouseholdAccess) -> bool:
    return access.grant is Grant.own and (
        row["owner_resident_id"] == str(access.resident_id)
        or (
            row["scope"] == "common" and row["registered_by_resident_id"] == str(access.resident_id)
        )
    )


def _view(row: sqlite3.Row, access: HouseholdAccess):
    base = dict(
        id=row["id"],
        household_id=row["household_id"],
        category=row["category"],
        typical_watts=row["typical_watts"],
        status=row["status"],
    )
    if access.grant is Grant.diagnostic:
        return ApplianceDiagnosticView(**base)
    return ApplianceView(
        **base,
        name=row["name"],
        ownership=ApplianceOwnership(
            scope=row["scope"],
            owner_resident_id=row["owner_resident_id"],
            home_room_id=row["home_room_id"],
        ),
    )


def list_appliances(conn: sqlite3.Connection, access: HouseholdAccess):
    rows = conn.execute(
        "SELECT a.*, s.scope, s.owner_resident_id, s.home_room_id, s.valid_from"
        " FROM appliance a JOIN appliance_state s ON s.id = ("
        " SELECT latest.id FROM appliance_state latest WHERE latest.appliance_id = a.id"
        " ORDER BY latest.valid_from DESC,latest.id DESC LIMIT 1)"
        " WHERE a.household_id = ? ORDER BY a.name, a.id",
        (str(access.household_id),),
    ).fetchall()
    return [_view(r, access) for r in rows if _can_read(r, access)]


def get_appliance(conn: sqlite3.Connection, access: HouseholdAccess, id: UUID):
    row = _current(conn, access.household_id, id)
    if row is None or not _can_read(row, access):
        raise _not_found()
    return _view(row, access)


def create_appliance(
    conn: sqlite3.Connection,
    access: HouseholdAccess,
    body: ApplianceCreate,
    at: datetime,
):
    if access.grant is not Grant.own:
        raise CatalogError(403, "forbidden_role", "Só inquilinos registam aparelhos")
    house, actor, when = access.household_id, access.resident_id, timestamp(at)
    owner = None if body.scope is ApplianceScope.common else actor
    _check_owner(conn, house, body.scope, owner, at)
    _check_room(conn, house, body.home_room_id)
    aid = new_id()
    conn.execute(
        "INSERT INTO appliance (id,household_id,name,category,typical_watts,"
        "registered_by_resident_id,status,created_at) VALUES (?,?,?,?,?,?,'active',?)",
        (
            str(aid),
            str(house),
            body.name,
            body.category.value,
            body.typical_watts,
            str(actor),
            when,
        ),
    )
    conn.execute(
        "INSERT INTO appliance_state (id,appliance_id,household_id,scope,"
        "owner_resident_id,home_room_id,valid_from,changed_by_resident_id)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            str(new_id()),
            str(aid),
            str(house),
            body.scope.value,
            str(owner) if owner else None,
            str(body.home_room_id) if body.home_room_id else None,
            when,
            str(actor),
        ),
    )
    return get_appliance(conn, access, aid)


def create_learned_appliance(
    conn: sqlite3.Connection,
    household_id: UUID,
    *,
    name: str,
    typical_watts: float,
    ownership: ApplianceOwnership,
    registered_by_resident_id: UUID,
    at: datetime,
) -> UUID:
    """ENERGY-04: aparelho nascido de «O que é este aparelho?» (categoria `other`).

    Mesmas validações de `create_appliance`: quem regista tem de ser inquilino ativo; um
    aparelho pessoal (ou partilhado) é de quem regista; um comum não tem dono; a divisão
    habitual tem de ser da casa. Um nome repetido de quem regista ganha « (2)», « (3)»…
    (o índice `appliance_active_duplicate` recusaria o duplicado).
    """
    house, actor, when = household_id, registered_by_resident_id, timestamp(at)
    if not _active_tenant(conn, house, actor, at):
        raise CatalogError(403, "forbidden_role", "Só inquilinos registam aparelhos")
    expected_owner = None if ownership.scope is ApplianceScope.common else actor
    if ownership.owner_resident_id != expected_owner:
        raise _invalid("Um aparelho pessoal é de quem o regista")
    _check_owner(conn, house, ownership.scope, ownership.owner_resident_id, at)
    _check_room(conn, house, ownership.home_room_id)
    if not 0 < typical_watts <= 100_000:
        raise _invalid("Potência típica inválida")
    base = name.strip()
    if not 1 <= len(base) <= 110:
        raise _invalid("Nome inválido")
    candidate, n = base, 1
    while conn.execute(
        "SELECT 1 FROM appliance WHERE household_id = ? AND registered_by_resident_id = ?"
        " AND category = 'other' AND lower(name) = lower(?) AND status = 'active'",
        (str(house), str(actor), candidate),
    ).fetchone():
        n += 1
        candidate = f"{base} ({n})"
    aid = new_id()
    conn.execute(
        "INSERT INTO appliance (id,household_id,name,category,typical_watts,"
        "registered_by_resident_id,status,created_at) VALUES (?,?,?,'other',?,?,'active',?)",
        (str(aid), str(house), candidate, typical_watts, str(actor), when),
    )
    conn.execute(
        "INSERT INTO appliance_state (id,appliance_id,household_id,scope,"
        "owner_resident_id,home_room_id,valid_from,changed_by_resident_id)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            str(new_id()),
            str(aid),
            str(house),
            ownership.scope.value,
            str(ownership.owner_resident_id) if ownership.owner_resident_id else None,
            str(ownership.home_room_id) if ownership.home_room_id else None,
            when,
            str(actor),
        ),
    )
    return aid


def _monotonic(when: str, start: str) -> None:
    if when <= start:
        raise CatalogError(409, "catalog_time_conflict", "Alterações exigem instantes crescentes")


def patch_appliance(
    conn: sqlite3.Connection,
    access: HouseholdAccess,
    id: UUID,
    body: AppliancePatch,
    at: datetime,
):
    row = _current(conn, access.household_id, id)
    if row is None or not _can_read(row, access):
        raise _not_found()
    if not _can_write(row, access):
        raise CatalogError(403, "forbidden_role", "Só o proprietário ou autor do comum edita")
    if row["status"] == "retired":
        raise CatalogError(409, "appliance_retired", "Aparelho retirado de serviço")
    fields = body.model_fields_set
    if not fields:
        return _view(row, access)
    for name in ("name", "category"):
        if name in fields and getattr(body, name) is None:
            raise _invalid(f"{name} não pode ser nulo")
    when = timestamp(at)
    house = access.household_id
    scope = body.scope if "scope" in fields else ApplianceScope(row["scope"])
    owner = (
        body.owner_resident_id
        if "owner_resident_id" in fields
        else UUID(row["owner_resident_id"])
        if row["owner_resident_id"]
        else None
    )
    if "scope" in fields and "owner_resident_id" not in fields:
        if scope is ApplianceScope.common:
            owner = None
        elif owner is None:
            owner = access.resident_id
    room = (
        body.home_room_id
        if "home_room_id" in fields
        else UUID(row["home_room_id"])
        if row["home_room_id"]
        else None
    )
    _check_owner(conn, house, scope, owner, at)
    _check_room(conn, house, room)
    changes_state = (
        scope.value != row["scope"]
        or (str(owner) if owner else None) != row["owner_resident_id"]
        or (str(room) if room else None) != row["home_room_id"]
    )
    if changes_state:
        _monotonic(when, row["valid_from"])
        conn.execute(
            "UPDATE appliance_state SET valid_to = ? WHERE appliance_id = ?"
            " AND valid_to IS NULL",
            (when, str(id)),
        )
        conn.execute(
            "INSERT INTO appliance_state (id,appliance_id,household_id,scope,"
            "owner_resident_id,home_room_id,valid_from,changed_by_resident_id)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                str(new_id()),
                str(id),
                str(house),
                scope.value,
                str(owner) if owner else None,
                str(room) if room else None,
                when,
                str(access.resident_id),
            ),
        )
    name = body.name if "name" in fields else row["name"]
    category = body.category.value if "category" in fields else row["category"]
    watts = body.typical_watts if "typical_watts" in fields else row["typical_watts"]
    conn.execute(
        "UPDATE appliance SET name = ?, category = ?, typical_watts = ? WHERE id = ?",
        (name, category, watts, str(id)),
    )
    return _view(_current(conn, access.household_id, id), access)


def retire_appliance(
    conn: sqlite3.Connection,
    access: HouseholdAccess,
    id: UUID,
    at: datetime,
):
    row = _current(conn, access.household_id, id)
    if row is None or not _can_read(row, access):
        raise _not_found()
    if not _can_write(row, access):
        raise CatalogError(403, "forbidden_role", "Sem permissão para retirar")
    if row["status"] == "retired":
        return _view(row, access)
    when = timestamp(at)
    state = conn.execute(
        "SELECT valid_from FROM appliance_state WHERE appliance_id = ? AND valid_to IS NULL",
        (str(id),),
    ).fetchone()
    if state is None:
        raise _not_found()
    _monotonic(when, state["valid_from"])
    link = conn.execute(
        "SELECT valid_from FROM appliance_meter_link"
        " WHERE appliance_id = ? AND valid_to IS NULL",
        (str(id),),
    ).fetchone()
    if link:
        _monotonic(when, link["valid_from"])
        conn.execute(
            "UPDATE appliance_meter_link SET valid_to = ?"
            " WHERE appliance_id = ? AND valid_to IS NULL",
            (when, str(id)),
        )
    conn.execute(
        "UPDATE appliance_state SET valid_to = ? WHERE appliance_id = ? AND valid_to IS NULL",
        (when, str(id)),
    )
    conn.execute(
        "UPDATE appliance SET status = 'retired', retired_at = ? WHERE id = ?",
        (when, str(id)),
    )
    return get_appliance(conn, access, id)


def state_history(conn: sqlite3.Connection, access: HouseholdAccess, id: UUID):
    row = _current(conn, access.household_id, id)
    if row is None or not _can_read(row, access):
        raise _not_found()
    records = conn.execute(
        "SELECT scope,owner_resident_id,home_room_id,valid_from,valid_to"
        " FROM appliance_state WHERE appliance_id = ? ORDER BY valid_from,id",
        (str(id),),
    ).fetchall()
    # Historical owners other than the caller must not be revealed to tenants.
    return [
        ApplianceHistoryView(
            scope=r["scope"],
            owner_resident_id=(
                r["owner_resident_id"]
                if r["owner_resident_id"] == str(access.resident_id) and access.grant is Grant.own
                else None
            ),
            home_room_id=r["home_room_id"],
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
        )
        for r in records
    ]


def register_device(conn: sqlite3.Connection, device: Device) -> DeviceView:
    """Internal P1 discovery upsert; MCP replay preserves the linked internal UUID."""
    existing = None
    if device.source.value == "mcp" and device.external_ref is not None:
        existing = conn.execute(
            "SELECT * FROM device WHERE household_id = ? AND source = 'mcp' AND external_ref = ?",
            (str(device.household_id), device.external_ref),
        ).fetchone()
    if existing is None:
        existing = conn.execute("SELECT * FROM device WHERE id = ?", (str(device.id),)).fetchone()
    if existing is not None and (
        existing["household_id"] != str(device.household_id)
        or existing["source"] != device.source.value
        or existing["external_ref"] != device.external_ref
    ):
        raise _invalid("A identidade do dispositivo não pode mudar de casa ou origem")
    if (
        existing is not None
        and existing["last_seen_at"] is not None
        and (
            device.last_seen_at is None or timestamp(device.last_seen_at) < existing["last_seen_at"]
        )
    ):
        return _device_view(existing)

    device_id = existing["id"] if existing is not None else str(device.id)
    values = (
        str(device.household_id),
        str(device.room_id) if device.room_id else None,
        device.name,
        device.kind.value,
        device.role.value,
        device.source.value,
        device.external_ref,
        device.power_unit.value,
        timestamp(device.last_seen_at) if device.last_seen_at else None,
        int(device.online),
    )
    if existing is None:
        conn.execute(
            "INSERT INTO device (id,household_id,room_id,name,kind,role,source,"
            "external_ref,power_unit,last_seen_at,online) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (device_id, *values),
        )
    else:
        conn.execute(
            "UPDATE device SET household_id=?,room_id=?,name=?,kind=?,role=?,source=?,"
            "external_ref=?,power_unit=?,last_seen_at=?,online=? WHERE id=?",
            (*values, device_id),
        )
    row = conn.execute("SELECT * FROM device WHERE id = ?", (device_id,)).fetchone()
    return _device_view(row)


def _device_view(row: sqlite3.Row) -> DeviceView:
    return DeviceView(
        id=row["id"],
        household_id=row["household_id"],
        room_id=row["room_id"],
        name=row["name"],
        kind=row["kind"],
        role=row["role"],
        source=row["source"],
        power_unit=row["power_unit"],
        last_seen_at=row["last_seen_at"],
        online=bool(row["online"]),
    )


def save_appliance_signature(
    conn: sqlite3.Connection, household_id: UUID, signature: ApplianceSignature
) -> None:
    """P1-owned, replay-safe signature persistence, constrained to the target household."""
    appliance = conn.execute(
        "SELECT household_id,status FROM appliance WHERE id = ?", (str(signature.appliance_id),)
    ).fetchone()
    if appliance is None or appliance["household_id"] != str(household_id):
        raise _not_found()
    if appliance["status"] != "active":
        raise CatalogError(409, "appliance_retired", "Aparelho retirado de serviço")
    existing = conn.execute(
        "SELECT appliance_id FROM appliance_signature WHERE id = ?", (str(signature.id),)
    ).fetchone()
    if existing is not None and existing["appliance_id"] != str(signature.appliance_id):
        raise _invalid("A assinatura não pode mudar de aparelho")
    conn.execute(
        "INSERT INTO appliance_signature (id,appliance_id,watts_mean,watts_tolerance,"
        "duration_typical_s,pattern,typical_hours_json,samples,origin,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
        " watts_mean=excluded.watts_mean,watts_tolerance=excluded.watts_tolerance,"
        " duration_typical_s=excluded.duration_typical_s,pattern=excluded.pattern,"
        " typical_hours_json=excluded.typical_hours_json,samples=excluded.samples,"
        " origin=excluded.origin,updated_at=excluded.updated_at"
        " WHERE excluded.updated_at > appliance_signature.updated_at"
        " OR (excluded.origin = 'learned'"
        " AND excluded.samples = appliance_signature.samples + 1)",
        (
            str(signature.id),
            str(signature.appliance_id),
            signature.watts_mean,
            signature.watts_tolerance,
            signature.duration_typical_s,
            signature.pattern.value,
            json.dumps(signature.typical_hours, separators=(",", ":"))
            if signature.typical_hours is not None
            else None,
            signature.samples,
            signature.origin.value,
            timestamp(signature.updated_at),
        ),
    )


def signatures_for_household(
    conn: sqlite3.Connection, household_id: UUID
) -> dict[UUID, list[ApplianceSignature]]:
    """Load current P1 signatures in one query, without crossing household scope."""
    rows = conn.execute(
        "SELECT s.* FROM appliance_signature s JOIN appliance a ON a.id = s.appliance_id"
        " WHERE a.household_id = ? AND a.status = 'active'"
        " ORDER BY s.appliance_id,s.updated_at,s.id",
        (str(household_id),),
    ).fetchall()
    result: dict[UUID, list[ApplianceSignature]] = {}
    for row in rows:
        signature = ApplianceSignature(
            id=row["id"],
            appliance_id=row["appliance_id"],
            watts_mean=row["watts_mean"],
            watts_tolerance=row["watts_tolerance"],
            duration_typical_s=row["duration_typical_s"],
            pattern=row["pattern"],
            typical_hours=json.loads(row["typical_hours_json"])
            if row["typical_hours_json"] is not None
            else None,
            samples=row["samples"],
            origin=row["origin"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        result.setdefault(signature.appliance_id, []).append(signature)
    return result


def provision_demo_device(
    conn: sqlite3.Connection,
    access: HouseholdAccess,
    body: DeviceCreateDemo,
):
    if access.grant is not Grant.diagnostic or body.source.value == "mcp":
        raise CatalogError(403, "forbidden_role", "Só o operador cria dispositivos de demo")
    _check_room(conn, access.household_id, body.room_id)
    device = Device(
        id=new_id(),
        household_id=access.household_id,
        room_id=body.room_id,
        name=body.name,
        kind=body.kind,
        role=body.role,
        source=body.source,
    )
    return register_device(conn, device)


def list_devices(conn: sqlite3.Connection, house: UUID) -> list[DeviceView]:
    rows = conn.execute(
        "SELECT * FROM device WHERE household_id = ? ORDER BY name,id", (str(house),)
    ).fetchall()
    return [DeviceView.of(Device(**{**dict(r), "online": bool(r["online"])})) for r in rows]


def set_meter(
    conn: sqlite3.Connection,
    access: HouseholdAccess,
    appliance_id: UUID,
    device_id: UUID | None,
    at: datetime,
) -> None:
    if access.grant is not Grant.diagnostic:
        raise CatalogError(403, "forbidden_role", "Só o operador associa medidores")
    appliance = _current(conn, access.household_id, appliance_id)
    if appliance is None:
        raise _not_found()
    if appliance["status"] != "active":
        raise CatalogError(409, "appliance_retired", "Aparelho retirado de serviço")
    if (
        device_id is not None
        and conn.execute(
            "SELECT 1 FROM device WHERE id = ? AND household_id = ?"
            " AND kind = 'plug' AND role IN ('main_meter','room_meter')",
            (str(device_id), str(access.household_id)),
        ).fetchone()
        is None
    ):
        raise _invalid("Medidor inexistente ou inválido nesta casa")
    active = conn.execute(
        "SELECT device_id,valid_from FROM appliance_meter_link"
        " WHERE appliance_id = ? AND valid_to IS NULL",
        (str(appliance_id),),
    ).fetchone()
    if (active["device_id"] if active else None) == (str(device_id) if device_id else None):
        return
    when = timestamp(at)
    if active:
        _monotonic(when, active["valid_from"])
        conn.execute(
            "UPDATE appliance_meter_link SET valid_to = ?"
            " WHERE appliance_id = ? AND valid_to IS NULL",
            (when, str(appliance_id)),
        )
    if device_id is not None:
        conn.execute(
            "INSERT INTO appliance_meter_link (id,appliance_id,device_id,household_id,"
            "valid_from,assigned_by_resident_id) VALUES (?,?,?,?,?,?)",
            (
                str(new_id()),
                str(appliance_id),
                str(device_id),
                str(access.household_id),
                when,
                str(access.resident_id),
            ),
        )


def meter_at(
    conn: sqlite3.Connection, household_id: UUID, appliance_id: UUID, at: datetime
) -> UUID | None:
    row = conn.execute(
        "SELECT device_id FROM appliance_meter_link WHERE household_id = ? AND appliance_id = ?"
        " AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        (str(household_id), str(appliance_id), timestamp(at), timestamp(at)),
    ).fetchone()
    return UUID(row["device_id"]) if row else None


def meters_for_period(
    conn: sqlite3.Connection,
    household_id: UUID,
    appliance_id: UUID,
    started_at: datetime,
    ended_at: datetime,
) -> list[MeterContextSegment]:
    """Resolve configured meter links over a period; a link is not usage evidence."""
    if ended_at < started_at:
        raise ValueError("ended_at anterior a started_at")
    start_text, end_text = timestamp(started_at), timestamp(ended_at)
    rows = conn.execute(
        "SELECT l.valid_from,l.valid_to,l.device_id FROM appliance a"
        " LEFT JOIN appliance_meter_link l ON l.household_id = a.household_id"
        " AND l.appliance_id = a.id AND (l.valid_to IS NULL OR l.valid_to > ?)"
        " AND l.valid_from <= ? WHERE a.household_id = ? AND a.id = ?"
        " ORDER BY l.valid_from,l.id",
        (
            start_text,
            end_text,
            str(household_id),
            str(appliance_id),
        ),
    ).fetchall()
    if not rows or rows[0]["valid_from"] is None:
        return [MeterContextSegment(started_at, ended_at, None)]
    links = [row for row in rows if row["valid_from"] is not None]
    boundaries = {started_at, ended_at}
    for row in links:
        link_start = datetime.fromisoformat(row["valid_from"])
        link_end = datetime.fromisoformat(row["valid_to"]) if row["valid_to"] else None
        if started_at < link_start < ended_at:
            boundaries.add(link_start)
        if link_end is not None and started_at < link_end < ended_at:
            boundaries.add(link_end)
    ordered = sorted(boundaries)
    if ended_at == started_at:
        ordered = [started_at, ended_at]
    return [
        MeterContextSegment(
            started_at=segment_start,
            ended_at=segment_end,
            device_id=next(
                (
                    UUID(row["device_id"])
                    for row in links
                    if datetime.fromisoformat(row["valid_from"]) <= segment_start
                    and (
                        row["valid_to"] is None
                        or segment_start < datetime.fromisoformat(row["valid_to"])
                    )
                ),
                None,
            ),
        )
        for segment_start, segment_end in zip(ordered, ordered[1:], strict=False)
    ]


def context_segments_for_consumption(
    conn: sqlite3.Connection, event: ConsumptionEvent
) -> list[ApplianceContextSegment]:
    """Return historical ownership segments; this is context, never payer attribution.

    Closed events are split at every catalogue boundary using [start, end). An
    ongoing event gets only a provisional snapshot at its start. Unknown matches
    have no appliance-specific context.
    """
    appliance_id = event.match.appliance_id
    if appliance_id is None:
        return []

    start = event.started_at
    end = event.ended_at
    if end is None:
        ownership = ownership_at(conn, event.household_id, appliance_id, start)
        return [
            ApplianceContextSegment(
                started_at=start,
                ended_at=None,
                ownership=ownership,
            )
        ]
    rows = conn.execute(
        "SELECT a.created_at,a.retired_at,s.scope,s.owner_resident_id,s.home_room_id,"
        "s.valid_from,s.valid_to FROM appliance a LEFT JOIN appliance_state s"
        " ON s.appliance_id = a.id WHERE a.household_id = ? AND a.id = ?"
        " ORDER BY s.valid_from,s.id",
        (str(event.household_id), str(appliance_id)),
    ).fetchall()
    if not rows:
        return [ApplianceContextSegment(start, end, None)]
    boundaries = {start, end}
    for row in rows:
        for column in ("created_at", "retired_at", "valid_from", "valid_to"):
            value = row[column]
            if value is not None:
                boundary = datetime.fromisoformat(value)
                if start < boundary < end:
                    boundaries.add(boundary)
    ordered = sorted(boundaries)
    if end == start:
        ordered = [start, end]
    result: list[ApplianceContextSegment] = []
    for segment_start, segment_end in zip(ordered, ordered[1:], strict=False):
        state = next(
            (
                row
                for row in rows
                if row["valid_from"] is not None
                and datetime.fromisoformat(row["valid_from"]) <= segment_start
                and (
                    row["valid_to"] is None
                    or segment_start < datetime.fromisoformat(row["valid_to"])
                )
                and datetime.fromisoformat(row["created_at"]) <= segment_start
                and (
                    row["retired_at"] is None
                    or segment_start < datetime.fromisoformat(row["retired_at"])
                )
            ),
            None,
        )
        result.append(
            ApplianceContextSegment(
                segment_start,
                segment_end,
                ApplianceOwnership(
                    scope=state["scope"],
                    owner_resident_id=state["owner_resident_id"],
                    home_room_id=state["home_room_id"],
                )
                if state is not None
                else None,
            )
        )
    return result


def ownership_at(
    conn: sqlite3.Connection,
    household_id: UUID,
    appliance_id: UUID,
    at: datetime,
) -> ApplianceOwnership | None:
    """Historical snapshot. For P4 use event.started_at, NEVER the current owner."""
    when = timestamp(at)
    row = conn.execute(
        "SELECT s.scope,s.owner_resident_id,s.home_room_id FROM appliance_state s"
        " JOIN appliance a ON a.id = s.appliance_id"
        " WHERE s.household_id = ? AND s.appliance_id = ?"
        " AND a.created_at <= ? AND (a.retired_at IS NULL OR a.retired_at > ?)"
        " AND s.valid_from <= ? AND (s.valid_to IS NULL OR s.valid_to > ?)",
        (str(household_id), str(appliance_id), when, when, when, when),
    ).fetchone()
    return ApplianceOwnership(**dict(row)) if row else None


def context_for_consumption(
    conn: sqlite3.Connection, event: ConsumptionEvent
) -> ApplianceOwnership | None:
    """Return one context only when the whole event has one unambiguous snapshot.

    A different meter does not invalidate a probable signature match. Unknown
    matches and events crossing ownership/location/retirement boundaries return
    None; use `context_segments_for_consumption` when P4 needs to inspect them.
    An appliance's owner does not identify who used it or who should pay.
    """
    segments = context_segments_for_consumption(conn, event)
    if len(segments) != 1 or segments[0].ownership is None:
        return None
    return segments[0].ownership


class SqliteApplianceCatalog:
    """HOUSE-03 implementation of the shared P1/P4 port.

    Consumers receive this adapter through composition/injection and import only
    ``contracts.appliance_catalog.ApplianceCatalog``. Every call uses the caller's
    connection so transaction and event-replay boundaries remain intact.
    """

    def device_location(
        self, conn: sqlite3.Connection, household_id: UUID, device_id: UUID
    ) -> DeviceLocation | None:
        row = conn.execute(
            "SELECT d.role,d.room_id,r.kind FROM device d LEFT JOIN room r"
            " ON r.id=d.room_id AND r.household_id=d.household_id"
            " WHERE d.household_id=? AND d.id=?",
            (str(household_id), str(device_id)),
        ).fetchone()
        if row is None:
            return None
        return DeviceLocation(
            role=DeviceRole(row["role"]),
            room_id=UUID(row["room_id"]) if row["room_id"] else None,
            room_kind=RoomKind(row["kind"]) if row["kind"] else None,
        )

    def appliances_for_household(
        self, conn: sqlite3.Connection, household_id: UUID, at: datetime
    ) -> list[ApplianceSnapshot]:
        when = timestamp(at)
        rows = conn.execute(
            "SELECT a.id,a.typical_watts,s.scope,s.owner_resident_id,s.home_room_id,"
            " l.device_id FROM appliance a JOIN appliance_state s"
            " ON s.appliance_id=a.id AND s.household_id=a.household_id"
            " AND s.valid_from<=? AND (s.valid_to IS NULL OR s.valid_to>?)"
            " LEFT JOIN appliance_meter_link l ON l.appliance_id=a.id"
            " AND l.household_id=a.household_id AND l.valid_from<=?"
            " AND (l.valid_to IS NULL OR l.valid_to>?)"
            " WHERE a.household_id=? AND a.created_at<=?"
            " AND (a.retired_at IS NULL OR a.retired_at>?) ORDER BY a.id",
            (when, when, when, when, str(household_id), when, when),
        ).fetchall()
        return [
            ApplianceSnapshot(
                appliance_id=UUID(r["id"]),
                ownership=ApplianceOwnership(
                    scope=r["scope"],
                    owner_resident_id=r["owner_resident_id"],
                    home_room_id=r["home_room_id"],
                ),
                typical_watts=r["typical_watts"],
                meter_device_id=UUID(r["device_id"]) if r["device_id"] else None,
            )
            for r in rows
        ]

    def register_device(self, conn: sqlite3.Connection, device: Device) -> DeviceView:
        return register_device(conn, device)

    def save_appliance_signature(
        self, conn: sqlite3.Connection, household_id: UUID, signature: ApplianceSignature
    ) -> None:
        save_appliance_signature(conn, household_id, signature)

    def signatures_for_household(
        self, conn: sqlite3.Connection, household_id: UUID
    ) -> dict[UUID, list[ApplianceSignature]]:
        return signatures_for_household(conn, household_id)

    def meter_at(
        self, conn: sqlite3.Connection, household_id: UUID, appliance_id: UUID, at: datetime
    ) -> UUID | None:
        return meter_at(conn, household_id, appliance_id, at)

    def meters_for_period(
        self,
        conn: sqlite3.Connection,
        household_id: UUID,
        appliance_id: UUID,
        started_at: datetime,
        ended_at: datetime,
    ) -> list[MeterContextSegment]:
        return meters_for_period(conn, household_id, appliance_id, started_at, ended_at)

    def ownership_at(
        self, conn: sqlite3.Connection, household_id: UUID, appliance_id: UUID, at: datetime
    ) -> ApplianceOwnership | None:
        return ownership_at(conn, household_id, appliance_id, at)

    def context_segments_for_consumption(
        self, conn: sqlite3.Connection, event: ConsumptionEvent
    ) -> list[ApplianceContextSegment]:
        return context_segments_for_consumption(conn, event)

    def context_for_consumption(
        self, conn: sqlite3.Connection, event: ConsumptionEvent
    ) -> ApplianceOwnership | None:
        return context_for_consumption(conn, event)

    def create_learned_appliance(
        self,
        conn: sqlite3.Connection,
        household_id: UUID,
        *,
        name: str,
        typical_watts: float,
        ownership: ApplianceOwnership,
        registered_by_resident_id: UUID,
        at: datetime,
    ) -> UUID:
        return create_learned_appliance(
            conn,
            household_id,
            name=name,
            typical_watts=typical_watts,
            ownership=ownership,
            registered_by_resident_id=registered_by_resident_id,
            at=at,
        )


def appliance_catalog() -> ApplianceCatalog:
    """Factory exposed to the composition root for transaction-scoped injection."""
    return SqliteApplianceCatalog()
