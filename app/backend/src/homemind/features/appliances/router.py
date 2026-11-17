"""House-scoped, RBAC-protected REST catalogue. All writes use core.db transactions."""

from __future__ import annotations

import sqlite3
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from homemind.contracts.devices import DeviceView
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.features.appliances import repo
from homemind.features.appliances.schemas import (
    ApplianceCreate,
    ApplianceDiagnosticView,
    ApplianceHistoryView,
    AppliancePatch,
    ApplianceView,
    DeviceCreateDemo,
    MeterAssignment,
    MeterAssignmentView,
)

router = APIRouter(prefix="/api/households/{household_id}", tags=["appliances"])
Read = Annotated[HouseholdAccess, Depends(require_access(Resource.appliance))]
Write = Annotated[HouseholdAccess, Depends(require_access(Resource.appliance, Operation.write))]
DeviceRead = Annotated[HouseholdAccess, Depends(require_access(Resource.device))]
DeviceWrite = Annotated[HouseholdAccess, Depends(require_access(Resource.device, Operation.write))]
Visible = ApplianceView | ApplianceDiagnosticView


async def _run(db, fn):
    try:
        return await db.run(fn)
    except repo.CatalogError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from None
    except sqlite3.IntegrityError:
        raise HTTPException(
            409, {"code": "catalog_conflict", "message": "Registo duplicado ou referência inválida"}
        ) from None
    except ValidationError:
        raise HTTPException(
            422, {"code": "invalid_request", "message": "Dados do catálogo inválidos"}
        ) from None


@router.get("/appliances")
async def list_appliances(access: Read, db: DbDep) -> list[Visible]:
    return await _run(db, lambda conn: repo.list_appliances(conn, access))


@router.post("/appliances", status_code=201)
async def create_appliance(
    body: ApplianceCreate,
    access: Write,
    db: DbDep,
    clock: ClockDep,
) -> Visible:
    return await _run(db, lambda conn: repo.create_appliance(conn, access, body, clock()))


@router.get("/appliances/{appliance_id}")
async def get_appliance(appliance_id: UUID, access: Read, db: DbDep) -> Visible:
    return await _run(db, lambda conn: repo.get_appliance(conn, access, appliance_id))


@router.patch("/appliances/{appliance_id}")
async def patch_appliance(
    appliance_id: UUID,
    body: AppliancePatch,
    access: Write,
    db: DbDep,
    clock: ClockDep,
) -> Visible:
    return await _run(
        db, lambda conn: repo.patch_appliance(conn, access, appliance_id, body, clock())
    )


@router.delete("/appliances/{appliance_id}")
async def retire_appliance(
    appliance_id: UUID,
    access: Write,
    db: DbDep,
    clock: ClockDep,
) -> Visible:
    """Soft retirement: historical ownership and meter links remain immutable."""
    return await _run(db, lambda conn: repo.retire_appliance(conn, access, appliance_id, clock()))


@router.get("/appliances/{appliance_id}/history")
async def appliance_history(
    appliance_id: UUID,
    access: Read,
    db: DbDep,
) -> list[ApplianceHistoryView]:
    return await _run(db, lambda conn: repo.state_history(conn, access, appliance_id))


@router.get("/devices")
async def list_devices(access: DeviceRead, db: DbDep) -> list[DeviceView]:
    """Operator diagnostics only. The MCP external reference is never serialized."""
    return await _run(db, lambda conn: repo.list_devices(conn, access.household_id))


@router.post("/devices/demo", status_code=201)
async def create_demo_device(
    body: DeviceCreateDemo,
    access: DeviceWrite,
    db: DbDep,
) -> DeviceView:
    """No physical operations; P1 provisions real MCP devices via register_device."""
    return await _run(db, lambda conn: repo.provision_demo_device(conn, access, body))


@router.put("/appliances/{appliance_id}/meter")
async def assign_meter(
    appliance_id: UUID,
    body: MeterAssignment,
    access: DeviceWrite,
    db: DbDep,
    clock: ClockDep,
) -> MeterAssignmentView:
    at = clock()

    def operation(conn):
        repo.set_meter(conn, access, appliance_id, body.device_id, at)
        actual = repo.meter_at(conn, appliance_id, at)
        return MeterAssignmentView(
            appliance_id=appliance_id,
            device_id=actual,
            effective_at=at,
        )

    return await _run(db, operation)
