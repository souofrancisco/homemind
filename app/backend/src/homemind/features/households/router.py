"""Leitura de casas, quartos, membros e contexto do utilizador (HOUSE-01, parcial).

IMPLEMENTADO: leituras e `presence_opt_in` próprio. PLANEADO: criar casas/quartos, convites e
fim de contrato (a escrita existe em `repo.py`, sem rota ainda).
"""

import sqlite3
from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator

from homemind.contracts.common import ContractModel
from homemind.contracts.household import (
    HouseholdPolicy,
    HouseholdView,
    MeContext,
    MembershipRole,
    MembershipSelfView,
    MemberView,
    ResidentView,
    RoomKind,
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
from homemind.features.households import membership_flow as flow

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
async def list_members(access: MemberAccess, db: DbDep, clock: ClockDep) -> list[MemberView]:
    """O senhorio vê contratos; o inquilino só membros ativos na data local."""
    now = clock()

    def query(conn):
        zone = conn.execute(
            "SELECT timezone FROM household WHERE id=?", (str(access.household_id),)
        ).fetchone()["timezone"]
        day = now.astimezone(ZoneInfo(zone)).date().isoformat()
        only_active = access.role is MembershipRole.tenant
        sql = (
            "SELECT m.id AS membership_id, m.resident_id, r.display_name, m.role, m.room_id,"
            " m.starts_on, m.ends_on, m.status FROM membership m"
            " JOIN resident r ON r.id=m.resident_id WHERE m.household_id=?"
        )
        if only_active:
            sql += (
                " AND m.status='active' AND m.starts_on <= ?"
                " AND (m.ends_on IS NULL OR m.ends_on >= ?)"
            )
        sql += " ORDER BY m.starts_on, r.display_name"
        params = (str(access.household_id), day, day) if only_active else (
            str(access.household_id),
        )
        return conn.execute(sql, params).fetchall()

    return [MemberView(**dict(row)) for row in await db.run(query)]

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


# HOUSE-02: comandos restritos, sem alterar a matriz/permissões F0.
RoomWriteAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.room, Operation.write))
]


class CreateRoom(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    kind: RoomKind
    included_wh: Annotated[int, Field(strict=True, ge=0)] | None = None


class CreateInvitation(ContractModel):
    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    email: Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    room_id: UUID
    starts_on: date
    ends_on: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("ends_on anterior a starts_on")
        return self


class InvitationIssued(ContractModel):
    invitation_id: UUID
    token: str
    expires_at: datetime


class RedeemInvitation(ContractModel):
    token: Annotated[str, Field(min_length=32, max_length=128)]


async def _execute(db: DbDep, action):
    try:
        return await db.run(action)
    except flow.FlowError as error:
        raise HTTPException(
            error.status, {"code": error.code, "message": error.message}
        ) from None
    except sqlite3.IntegrityError:
        raise HTTPException(
            409, {"code": "membership_conflict", "message": "Estado em conflito"}
        ) from None


@router.post("/households/{household_id}/rooms", status_code=201)
async def create_house_room(
    body: CreateRoom, access: RoomWriteAccess, user: CurrentUser, db: DbDep, clock: ClockDep
) -> RoomView:
    return await _execute(
        db, lambda conn: flow.create_room(conn, user, access.household_id, body, clock())
    )


@router.post("/households/{household_id}/invitations", status_code=201)
async def create_house_invitation(
    body: CreateInvitation, access: MemberWriteAccess, user: CurrentUser,
    db: DbDep, clock: ClockDep,
) -> InvitationIssued:
    # MemberWriteAccess permite ao inquilino editar o seu consentimento.
    if access.role is not MembershipRole.landlord:
        raise HTTPException(403, {"code": "forbidden_role", "message": "Sem permissão"})
    result = await _execute(
        db, lambda conn: flow.issue_invitation(
            conn, user, access.household_id, body, clock()
        )
    )
    return InvitationIssued(**result)


@router.post("/invitations/accept")
async def redeem_house_invitation(
    body: RedeemInvitation, user: CurrentUser, db: DbDep, clock: ClockDep
) -> MembershipSelfView:
    return await _execute(
        db, lambda conn: flow.accept_invitation(conn, user, body.token, clock())
    )


@router.post("/households/{household_id}/memberships/{membership_id}/revoke")
async def revoke_house_membership(
    membership_id: UUID, access: MemberWriteAccess, user: CurrentUser,
    db: DbDep, clock: ClockDep,
) -> MemberView:
    if access.role is not MembershipRole.landlord:
        raise HTTPException(403, {"code": "forbidden_role", "message": "Sem permissão"})
    return await _execute(
        db, lambda conn: flow.revoke_membership(
            conn, user, access.household_id, membership_id, clock()
        )
    )
