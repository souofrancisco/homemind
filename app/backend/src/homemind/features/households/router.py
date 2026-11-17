"""Leitura de casas, quartos, membros e contexto do utilizador (HOUSE-01, parcial).

IMPLEMENTADO: leituras e `presence_opt_in` próprio. PLANEADO: criar casas/quartos, convites e
fim de contrato (a escrita existe em `repo.py`, sem rota ainda).
"""

from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from homemind.contracts.common import ContractModel
from homemind.contracts.household import (
    HouseholdPolicy,
    HouseholdView,
    MeContext,
    MembershipRole,
    MembershipSelfView,
    MemberView,
    ResidentView,
    RoomView,
    SourceKind,
)
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.features.auth.service import CurrentUser

router = APIRouter(prefix="/api", tags=["households"])

Access = Annotated[HouseholdAccess, Depends(require_access(Resource.household))]
RoomAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.room))]
MemberAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.member))]
MemberWriteAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.member, Operation.write))
]


@router.get("/me/context")
async def my_context(user: CurrentUser, db: DbDep, clock: ClockDep) -> MeContext:
    """O residente ligado ao `sub` e as suas memberships ativas (para escolher casa/papel).
    «Hoje» conta no fuso de cada casa, como em `find_membership`."""
    now = clock()

    def query(conn):
        resident = conn.execute(
            "SELECT id, display_name FROM resident WHERE auth_subject = ?", (user.sub,)
        ).fetchone()
        if resident is None:
            return None, []
        rows = conn.execute(
            "SELECT m.id, m.household_id, m.role, m.room_id, m.starts_on, m.ends_on, m.status,"
            " m.presence_opt_in, h.timezone FROM membership m JOIN household h"
            " ON h.id = m.household_id WHERE m.resident_id = ? AND m.status = 'active'"
            " ORDER BY m.starts_on, m.id",
            (resident["id"],),
        ).fetchall()
        return resident, rows

    resident, rows = await db.run(query)
    memberships = []
    for r in rows:
        today = now.astimezone(ZoneInfo(r["timezone"])).date().isoformat()
        if r["starts_on"] <= today and (r["ends_on"] is None or r["ends_on"] >= today):
            data = {k: r[k] for k in r.keys() if k != "timezone"}
            memberships.append(
                MembershipSelfView(**{**data, "presence_opt_in": bool(r["presence_opt_in"])})
            )
    return MeContext(
        resident=ResidentView(id=resident["id"], display_name=resident["display_name"])
        if resident
        else None,
        memberships=memberships,
    )


@router.get("/households/{household_id}")
async def get_household(access: Access, db: DbDep) -> HouseholdView:
    row = await db.run(
        lambda c: c.execute(
            "SELECT * FROM household WHERE id = ?", (str(access.household_id),)
        ).fetchone()
    )
    return HouseholdView(
        id=row["id"],
        name=row["name"],
        timezone=row["timezone"],
        source_kind=SourceKind(row["source_kind"]),
        policy=HouseholdPolicy(
            common_area_rule=row["common_area_rule"],
            ask_threshold_cents=row["ask_threshold_cents"],
            ask_timeout_hours=row["ask_timeout_hours"],
        ),
    )


@router.get("/households/{household_id}/rooms")
async def list_rooms(access: RoomAccess, db: DbDep) -> list[RoomView]:
    rows = await db.run(
        lambda c: c.execute(
            "SELECT id, name, kind FROM room WHERE household_id = ? ORDER BY name",
            (str(access.household_id),),
        ).fetchall()
    )
    return [RoomView(**dict(r)) for r in rows]


@router.get("/households/{household_id}/members")
async def list_members(access: MemberAccess, db: DbDep) -> list[MemberView]:
    """Moradores e contratos. Nunca `presence_opt_in`, `sub` nem contactos de terceiros.
    O senhorio vê todos os estados; um inquilino só vê quem está ativo."""
    only_active = access.role is MembershipRole.tenant
    rows = await db.run(
        lambda c: c.execute(
            "SELECT m.id AS membership_id, m.resident_id, r.display_name, m.role, m.room_id,"
            " m.starts_on, m.ends_on, m.status FROM membership m"
            " JOIN resident r ON r.id = m.resident_id WHERE m.household_id = ?"
            + (" AND m.status = 'active'" if only_active else "")
            + " ORDER BY m.starts_on, r.display_name",
            (str(access.household_id),),
        ).fetchall()
    )
    return [MemberView(**dict(r)) for r in rows]


class MembershipPatch(ContractModel):
    """Um inquilino só pode alterar o seu consentimento de presença."""

    presence_opt_in: Annotated[bool, Field(strict=True)]


@router.patch("/households/{household_id}/memberships/{membership_id}")
async def patch_membership(
    membership_id: UUID, body: MembershipPatch, access: MemberWriteAccess, db: DbDep
) -> MembershipSelfView:
    if access.role is not MembershipRole.tenant:  # o senhorio não decide o consentimento alheio
        raise HTTPException(403, {"code": "forbidden_role", "message": "Sem permissão"})

    def update(conn):
        row = conn.execute(
            "SELECT id, resident_id FROM membership WHERE id = ? AND household_id = ?",
            (str(membership_id), str(access.household_id)),
        ).fetchone()
        if row is None:
            return "missing"
        if row["id"] != str(access.membership_id):  # nunca a membership de outro
            return "forbidden"
        conn.execute(
            "UPDATE membership SET presence_opt_in = ? WHERE id = ?",
            (int(body.presence_opt_in), row["id"]),
        )
        return conn.execute(
            "SELECT id, household_id, role, room_id, starts_on, ends_on, status, presence_opt_in"
            " FROM membership WHERE id = ?",
            (row["id"],),
        ).fetchone()

    result = await db.run(update)
    if result == "missing":
        raise HTTPException(404, {"code": "household_not_found", "message": "Não encontrado"})
    if result == "forbidden":
        raise HTTPException(403, {"code": "forbidden_role", "message": "Sem permissão"})
    return MembershipSelfView(
        **{**dict(result), "presence_opt_in": bool(result["presence_opt_in"])}
    )
