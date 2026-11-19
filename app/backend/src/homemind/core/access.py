"""Autorização no servidor: contexto de casa e papel, e a matriz papel × recurso × operação.

O `sub` do Authentik só identifica o utilizador; casa, quarto e papel vêm das memberships na
base de dados (decisão P-02). Nunca se confia num `resident_id` enviado pelo cliente.

Regras de resposta (para não revelar o que existe):
- sem membership ativa na casa (ou casa inexistente) → 404 `household_not_found`;
- membership ativa mas papel sem acesso ao recurso → 403 `forbidden_role`.
O `Grant` diz com que âmbito o papel acede; os routers escolhem o DTO e filtram em função dele.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request

from homemind.contracts.household import MembershipRole
from homemind.core.db import Database
from homemind.features.auth.service import CurrentUser


class Resource(StrEnum):
    household = "household"
    room = "room"
    member = "member"  # membership de moradores (nomes, quartos, datas)
    device = "device"  # tomadas, lâmpadas (diagnóstico)
    appliance = "appliance"
    energy = "energy"  # leituras e resumos
    consumption = "consumption"  # episódios de consumo
    presence = "presence"  # quem está em casa
    camera_status = "camera_status"  # diagnóstico da câmara (sem imagens)
    attribution = "attribution"
    house_rules = "house_rules"  # regra da sala versionada (HOUSE-04)
    bill = "bill"
    receipt = "receipt"  # alocações e recibos
    budget = "budget"
    notification = "notification"
    agent = "agent"
    automation = "automation"
    simulation = "simulation"


class Operation(StrEnum):
    read = "read"
    write = "write"


class Grant(StrEnum):
    none = "none"
    own = "own"  # só os seus dados
    household = "household"  # dados da casa visíveis aos moradores
    aggregate = "aggregate"  # só totais (senhorio)
    diagnostic = "diagnostic"  # estado técnico, sem dados pessoais (operador)


LL, TT, OP = MembershipRole.landlord, MembershipRole.tenant, MembershipRole.operator
N, OWN, HH, AGG, DIAG = Grant.none, Grant.own, Grant.household, Grant.aggregate, Grant.diagnostic
R, W = Operation.read, Operation.write

# recurso -> operação -> papel -> âmbito. Ausente = `none`. É a única fonte da matriz.
PERMISSIONS: dict[Resource, dict[Operation, dict[MembershipRole, Grant]]] = {
    Resource.household: {R: {LL: HH, TT: HH, OP: DIAG}, W: {LL: HH}},
    Resource.room: {R: {LL: HH, TT: HH, OP: DIAG}, W: {LL: HH}},
    Resource.member: {R: {LL: HH, TT: HH}, W: {LL: HH, TT: OWN}},  # T só `presence_opt_in` próprio
    Resource.device: {R: {OP: DIAG}, W: {OP: DIAG}},
    Resource.appliance: {R: {TT: OWN, OP: DIAG}, W: {TT: OWN, OP: DIAG}},
    Resource.energy: {R: {LL: AGG, TT: OWN, OP: DIAG}},
    Resource.consumption: {R: {TT: HH, OP: DIAG}, W: {TT: OWN}},  # W: contestar
    Resource.presence: {R: {TT: OWN}, W: {TT: OWN}},  # nem co-moradores recebem estados individuais
    Resource.camera_status: {R: {OP: DIAG}},
    Resource.attribution: {R: {TT: OWN}},
    Resource.house_rules: {R: {LL: HH, TT: HH}, W: {TT: HH}},  # a casa escolhe; senhorio lê
    Resource.bill: {R: {LL: AGG, TT: OWN}, W: {LL: HH}},
    Resource.receipt: {R: {LL: AGG, TT: OWN}, W: {TT: OWN}},  # W: contestar
    Resource.budget: {R: {TT: OWN}, W: {TT: OWN}},
    Resource.notification: {R: {LL: OWN, TT: OWN}, W: {LL: OWN, TT: OWN}},
    Resource.agent: {R: {TT: OWN}, W: {TT: OWN}},
    # regras da casa votadas (SAFE-04): só moradores; nem senhorio nem operador as veem
    Resource.automation: {R: {TT: HH}, W: {TT: HH}},
    Resource.simulation: {W: {OP: DIAG}},
}


def grant_for(role: MembershipRole, resource: Resource, op: Operation) -> Grant:
    return PERMISSIONS.get(resource, {}).get(op, {}).get(role, Grant.none)


@dataclass(frozen=True)
class HouseholdAccess:
    """Quem pede, em que casa, com que papel. Sempre derivado da base de dados."""

    household_id: UUID
    resident_id: UUID
    membership_id: UUID
    role: MembershipRole
    room_id: UUID | None
    grant: Grant


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def find_membership(
    conn: sqlite3.Connection, sub: str, household_id: UUID, now: datetime
) -> sqlite3.Row | None:
    """Membership ativa e dentro de datas (no fuso da casa). `ends_on` passado = sem acesso,
    mesmo que o estado ainda diga `active`."""
    house = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()
    if house is None:
        return None
    today = now.astimezone(ZoneInfo(house["timezone"])).date().isoformat()
    return conn.execute(
        "SELECT m.id, m.resident_id, m.role, m.room_id FROM membership m"
        " JOIN resident r ON r.id = m.resident_id"
        " WHERE r.auth_subject = ? AND m.household_id = ? AND m.status = 'active'"
        " AND m.starts_on <= ? AND (m.ends_on IS NULL OR m.ends_on >= ?)",
        (sub, str(household_id), today, today),
    ).fetchone()


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_clock() -> Callable[[], datetime]:
    return lambda: datetime.now(UTC)


DbDep = Annotated[Database, Depends(get_db)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]


async def resolve_access(
    db: Database,
    sub: str,
    household_id: UUID,
    resource: Resource,
    op: Operation,
    now: datetime,
) -> HouseholdAccess:
    row = await db.run(lambda c: find_membership(c, sub, household_id, now))
    if row is None:
        raise _error(404, "household_not_found", "Casa não encontrada")
    role = MembershipRole(row["role"])
    grant = grant_for(role, resource, op)
    if grant is Grant.none:
        raise _error(403, "forbidden_role", "Sem permissão para este recurso")
    return HouseholdAccess(
        household_id=household_id,
        resident_id=UUID(row["resident_id"]),
        membership_id=UUID(row["id"]),
        role=role,
        room_id=UUID(row["room_id"]) if row["room_id"] else None,
        grant=grant,
    )


def require_access(resource: Resource, op: Operation = Operation.read):
    """Dependência para rotas com `{household_id}` no caminho:
    `access: Annotated[HouseholdAccess, Depends(require_access(Resource.bill))]`."""

    async def dependency(
        household_id: UUID, user: CurrentUser, db: DbDep, clock: ClockDep
    ) -> HouseholdAccess:
        return await resolve_access(db, user.sub, household_id, resource, op, clock())

    return dependency


async def require_operator(user: CurrentUser, db: DbDep, clock: ClockDep) -> None:
    """A rota não tem casa no caminho: exige papel `operator` numa membership ativa. Senhorio,
    inquilino ou sem membership recebem 403 (nunca se revela o que existe)."""
    now = clock()

    def query(conn) -> bool:
        casas = conn.execute(
            "SELECT DISTINCT m.household_id FROM membership m JOIN resident r"
            " ON r.id = m.resident_id WHERE r.auth_subject = ? AND m.role = ?",
            (user.sub, MembershipRole.operator.value),
        ).fetchall()
        for (casa,) in casas:
            row = find_membership(conn, user.sub, UUID(casa), now)
            if row is not None and row["role"] == MembershipRole.operator.value:
                return True
        return False

    if not await db.run(query):
        raise HTTPException(403, {"code": "forbidden_role", "message": "Sem permissão"})
