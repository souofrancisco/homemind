"""Segurança: consumidor no barramento (AWAY simulado) e painel de segurança SIMULADO (SAFE-02).

Rotas só para moradores (`Resource.security`): o senhorio e o operador recebem 403 e quem não é
membro da casa, 404 (`core/access.py`). O residente vem do token. Armar/desarmar são duas fases
(proposta → confirmação humana) e só mudam o painel SIMULADO: nada chama MCP, conectores nem
hardware (`ENABLE_PHYSICAL_WRITES` não é lido). Os eventos já estão no outbox; depois do COMMIT
acorda-se o barramento (uma falha só atrasa a entrega). Sem MCP real (D-07/P-01, MCP-04).
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from starlette.datastructures import State

from homemind.contracts.common import ContractModel
from homemind.contracts.safety import AwayStatus, SecurityActionKind
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.features.safety import security
from homemind.features.safety.service import SafetyService

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sem resolvedor de aquecedores (ENERGY-03 pendente): só as regras de fumo ficam ativas.
    service = SafetyService()
    service.attach(app.state.bus)
    app.state.safety = service
    log.info("safety: consumidor subscrito (janela+aquecedor aguarda ENERGY-03)")
    yield


router = APIRouter(prefix="/api", tags=["safety"], lifespan=lifespan)

ReadAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.security, Operation.read))]
WriteAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.security, Operation.write))
]

_ERRORS = {
    security.NOT_FOUND: (404, "Proposta não encontrada"),
    security.NOT_PENDING: (409, "Esta proposta já foi decidida"),
    security.EXPIRED: (409, "A proposta caducou; propõe de novo"),
    security.PENDING_EXISTS: (409, "Já há uma proposta à espera de confirmação"),
    security.NOT_APPLICABLE: (409, "O painel simulado já está nesse estado"),
    security.UNAVAILABLE: (409, "Esta casa não tem painel de segurança simulado"),
}


class SecurityProposeIn(ContractModel):
    kind: SecurityActionKind


def get_state(request: Request) -> State:
    return request.app.state


StateDep = Annotated[State, Depends(get_state)]


def _away(state: State, household_id: UUID) -> AwayStatus:
    service = getattr(state, "safety", None)
    return service.engine.away_status(household_id) if service else AwayStatus.unknown


async def _finish(state: State, result: security.Result) -> security.SecurityView:
    for event in result.events:
        try:
            await state.bus.publish(event)
        except Exception as e:  # noqa: BLE001 - o evento já está no outbox; só vai o tipo
            log.warning("falha a publicar %s (%s)", event.type, type(e).__name__)
    if result.error:
        status, message = _ERRORS[result.error]
        raise HTTPException(status, {"code": result.error, "message": message})
    assert result.view is not None
    return result.view


@router.get("/households/{household_id}/security")
async def get_security(
    access: ReadAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> security.SecurityView:
    away = _away(state, access.household_id)
    now = clock()
    return await db.run(lambda c: security.get_view(c, access.household_id, away, now))


@router.post("/households/{household_id}/security/proposals", status_code=201)
async def propose_security(
    body: SecurityProposeIn, access: WriteAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> security.SecurityView:
    """Fase 1: só regista a proposta (SIMULADA). Nada muda até um morador a confirmar."""
    away, now = _away(state, access.household_id), clock()
    result = await db.run(lambda c: security.propose(c, access.household_id, body.kind, away, now))
    return await _finish(state, result)


async def _decide(
    action_id: UUID, confirm: bool, access, db, clock, state
) -> security.SecurityView:
    away, now = _away(state, access.household_id), clock()
    result = await db.run(
        lambda c: security.decide(
            c, access.household_id, access.resident_id, action_id, confirm, away, now
        )
    )
    return await _finish(state, result)


@router.post("/households/{household_id}/security/proposals/{action_id}/confirm")
async def confirm_security(
    action_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> security.SecurityView:
    """Fase 2: confirmação humana explícita. Só muda o painel SIMULADO."""
    return await _decide(action_id, True, access, db, clock, state)


@router.post("/households/{household_id}/security/proposals/{action_id}/cancel")
async def cancel_security(
    action_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> security.SecurityView:
    return await _decide(action_id, False, access, db, clock, state)
