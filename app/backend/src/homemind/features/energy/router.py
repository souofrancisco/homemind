"""House-scoped signature inspection and explicit pattern locks."""

import json
import sqlite3
from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from homemind.contracts.common import ContractModel, UtcDatetime, stable_id
from homemind.contracts.devices import SignatureOrigin, SignaturePattern
from homemind.core.access import (
    ClockDep,
    DbDep,
    Grant,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)

router = APIRouter(prefix="/api/households/{household_id}", tags=["energy"])
Read = Annotated[HouseholdAccess, Depends(require_access(Resource.appliance))]
Write = Annotated[HouseholdAccess, Depends(require_access(Resource.appliance, Operation.write))]


class SignaturePatch(ContractModel):
    model_config = ContractModel.model_config | {"extra": "forbid"}
    pattern: SignaturePattern


class SignatureDiagnosticView(ContractModel):
    appliance_id: UUID
    watts_mean: float
    watts_tolerance: float
    duration_typical_s: int | None
    pattern: SignaturePattern
    pattern_locked: bool
    samples: int
    origin: SignatureOrigin
    updated_at: UtcDatetime


class SignatureView(SignatureDiagnosticView):
    typical_hours: list[int] | None


Visible = SignatureView | SignatureDiagnosticView


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _rows(conn: sqlite3.Connection, access: HouseholdAccess) -> list[sqlite3.Row]:
    # Match HOUSE-03 current visibility: diagnostic, common, or caller's ownership.
    return conn.execute(
        "SELECT sig.*,a.registered_by_resident_id,s.scope,s.owner_resident_id,"
        " lock.pattern AS locked_pattern FROM appliance_signature sig"
        " JOIN appliance a ON a.id=sig.appliance_id"
        " JOIN appliance_state s ON s.id=(SELECT latest.id FROM appliance_state latest"
        " WHERE latest.appliance_id=a.id ORDER BY latest.valid_from DESC,latest.id DESC LIMIT 1)"
        " LEFT JOIN energy_signature_lock lock ON lock.signature_id=sig.id"
        " WHERE a.household_id=? AND a.status='active'"
        " AND (? OR s.scope='common' OR s.owner_resident_id=?) ORDER BY a.id,sig.id",
        (str(access.household_id), access.grant is Grant.diagnostic, str(access.resident_id)),
    ).fetchall()


def _view(row: sqlite3.Row, access: HouseholdAccess) -> Visible:
    data = {
        name: row[name]
        for name in SignatureDiagnosticView.model_fields
        if name not in {"pattern_locked", "pattern"}
    }
    data["pattern"] = row["locked_pattern"] or row["pattern"]
    data["pattern_locked"] = row["locked_pattern"] is not None
    if access.grant is Grant.diagnostic:
        return SignatureDiagnosticView(**data)
    return SignatureView(
        **data,
        typical_hours=json.loads(row["typical_hours_json"])
        if row["typical_hours_json"] is not None
        else None,
    )


async def _run(db, fn):
    try:
        return await db.run(fn)
    except sqlite3.IntegrityError:
        raise _error(409, "signature_conflict", "Conflito ao guardar assinatura") from None
    except ValidationError:
        raise _error(422, "invalid_request", "Dados da assinatura inválidos") from None


@router.get("/energy/signatures")
async def list_signatures(access: Read, db: DbDep) -> list[Visible]:
    return await _run(db, lambda conn: [_view(r, access) for r in _rows(conn, access)])


@router.patch("/energy/signatures/{appliance_id}")
async def patch_signature(
    appliance_id: UUID,
    body: SignaturePatch,
    access: Write,
    db: DbDep,
    clock: ClockDep,
) -> Visible:
    def operation(conn):
        sid = str(stable_id("energy.signature", str(appliance_id)))
        row = next(
            (
                r
                for r in _rows(conn, access)
                if r["appliance_id"] == str(appliance_id) and r["id"] == sid
            ),
            None,
        )
        if row is None:
            raise _error(404, "signature_not_found", "Assinatura não encontrada")
        if access.grant is not Grant.own or not (
            row["owner_resident_id"] == str(access.resident_id)
            or (
                row["scope"] == "common"
                and row["registered_by_resident_id"] == str(access.resident_id)
            )
        ):
            raise _error(403, "forbidden_role", "Sem permissão para corrigir este aparelho")
        conn.execute(
            "UPDATE appliance_signature SET pattern=? WHERE id=?", (body.pattern.value, sid)
        )
        conn.execute(
            "INSERT INTO energy_signature_lock(signature_id,pattern,locked_at) VALUES (?,?,?)"
            " ON CONFLICT(signature_id) DO UPDATE SET"
            " pattern=excluded.pattern,locked_at=excluded.locked_at",
            (sid, body.pattern.value, clock().astimezone(UTC).isoformat(timespec="microseconds")),
        )
        return _view(next(r for r in _rows(conn, access) if r["id"] == sid), access)

    return await _run(db, operation)
