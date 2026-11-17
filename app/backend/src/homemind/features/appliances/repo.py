"""SQLite catalogue. Transactions are supplied by core.db; no MCP or billing logic."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.common import new_id
from homemind.contracts.devices import (
    ApplianceOwnership,
    ApplianceScope,
    Device,
    DeviceView,
)
from homemind.contracts.energy import ConsumptionEvent
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
        " FROM appliance a JOIN appliance_state s ON s.appliance_id = a.id"
        " AND s.valid_to IS NULL WHERE a.id = ? AND a.household_id = ?",
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
        " FROM appliance a JOIN appliance_state s ON s.appliance_id = a.id"
        " AND s.valid_to IS NULL WHERE a.household_id = ? ORDER BY a.name, a.id",
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
    return get_appliance(conn, access, id)


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
    """Internal entrypoint for P1 discovery. external_ref stays in the database."""
    conn.execute(
        "INSERT INTO device (id,household_id,room_id,name,kind,role,source,"
        "external_ref,power_unit,last_seen_at,online) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(device.id),
            str(device.household_id),
            str(device.room_id) if device.room_id else None,
            device.name,
            device.kind.value,
            device.role.value,
            device.source.value,
            device.external_ref,
            device.power_unit.value,
            device.last_seen_at.isoformat() if device.last_seen_at else None,
            int(device.online),
        ),
    )
    return DeviceView.of(device)


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


def meter_at(conn: sqlite3.Connection, appliance_id: UUID, at: datetime) -> UUID | None:
    row = conn.execute(
        "SELECT device_id FROM appliance_meter_link WHERE appliance_id = ?"
        " AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        (str(appliance_id), timestamp(at), timestamp(at)),
    ).fetchone()
    return UUID(row["device_id"]) if row else None


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


def context_for_consumption(conn: sqlite3.Connection, event: ConsumptionEvent):
    """P1/P4 integration: candidate match is uncertain; no financial attribution here.

    A different meter does not invalidate a probable signature match, and an
    appliance's owner does not identify who used it or who should pay.
    """
    if event.match.appliance_id is None:
        return None
    return ownership_at(conn, event.household_id, event.match.appliance_id, event.started_at)
