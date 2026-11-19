"""Regras da casa votadas (SAFE-04): propor, listar, votar, suspender e reativar.

Só inquilinos (`Resource.automation`): o senhorio e o operador recebem 403 e quem não é membro da
casa, 404 (padrão de `core/access.py`). O residente vem sempre do token; uma regra de outra casa
é 404. Nenhuma rota executa nada: o motor é PLANEADO. A resposta é a `AutomationView` (só
contagens, nunca quem votou o quê). Os eventos já estão no outbox; depois do COMMIT acorda-se o
barramento (uma falha só atrasa a entrega).
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from starlette.datastructures import State

from homemind.contracts.common import Origin
from homemind.contracts.devices import DeviceKind
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.core.db import Database
from homemind.features.agent.devices import select_directory
from homemind.features.automations import service
from homemind.features.automations.service import (
    AutomationProposeIn,
    AutomationStatusIn,
    AutomationView,
    AutomationVoteIn,
    ConflictError,
    Result,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["automations"])

ReadAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.automation, Operation.read))
]
WriteAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.automation, Operation.write))
]

_ERRORS = {
    service.NOT_FOUND: (404, "Regra não encontrada"),
    service.NOT_ELIGIBLE: (403, "Só os inquilinos da casa participam nesta votação"),
    service.INVALID_TARGET: (400, "A regra só pode desligar uma tomada conhecida da casa"),
    service.VOTE_NOT_OPEN: (409, "Esta regra não tem votação aberta"),
    service.VOTE_EXPIRED: (409, "O prazo da votação acabou; a regra foi rejeitada"),
    service.ALREADY_VOTED: (409, "Já votaste nesta regra"),
    service.NOT_ACTIVE: (409, "A regra não está ativa"),
    service.NOT_DISABLED: (409, "A regra não está suspensa"),
    service.VOTE_ALREADY_OPEN: (409, "Já há uma votação aberta para reativar esta regra"),
    service.TOO_MANY_OPEN: (
        409,
        "Já tens 3 votações abertas. Espera que sejam decididas antes de propor ou reativar outra",
    ),
    service.CONFLICT: (409, "A regra mudou entretanto; tenta de novo"),
}


def get_state(request: Request) -> State:
    return request.app.state


StateDep = Annotated[State, Depends(get_state)]


def _error(code: str) -> HTTPException:
    status, message = _ERRORS[code]
    return HTTPException(status, {"code": code, "message": message})


async def _wake(state: State, events) -> None:
    """Depois do COMMIT: acorda os consumidores. O evento já está no outbox, por isso uma falha
    aqui só atrasa a entrega e nunca falha o pedido."""
    for event in events:
        try:
            await state.bus.publish(event)
        except Exception as e:  # noqa: BLE001 - só o tipo vai para o log
            log.warning("falha a publicar %s (%s)", event.type, type(e).__name__)


async def _finish(state: State, result: Result) -> AutomationView:
    await _wake(state, result.events)
    if result.error:
        raise _error(result.error)
    assert result.view is not None
    return result.view


async def _run(db: Database, state: State, fn) -> AutomationView:
    try:
        result = await db.run(fn)
    except ConflictError:
        raise _error(service.CONFLICT) from None
    return await _finish(state, result)


@router.get("/households/{household_id}/automations")
async def list_automations(
    access: ReadAccess,
    db: DbDep,
    clock: ClockDep,
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AutomationView]:
    """As regras da casa, da mais recente à mais antiga. Uma votação fora de prazo resolve-se
    aqui (rejeitada), de forma idempotente."""
    now = clock()
    views, events = await db.run(
        lambda c: service.list_views(c, access.household_id, access.resident_id, now, limit)
    )
    await _wake(state, events)
    return views


@router.post("/households/{household_id}/automations", status_code=201)
async def propose_automation(
    body: AutomationProposeIn, access: WriteAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> AutomationView:
    """Propõe uma regra: fica `proposed`, por votar, e nada é executado. O alvo tem de ser uma
    tomada conhecida da casa (a lâmpada nunca)."""
    household_id = access.household_id
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()
    )
    source_kind = row["source_kind"]
    devices = select_directory(state, household_id, source_kind).actuators(household_id)
    if source_kind != "demo":  # uma casa real nunca usa dispositivos simulados
        devices = [d for d in devices if not d.simulated]
    plugs = {d.id: d.name for d in devices if d.kind is DeviceKind.plug}
    origin = Origin.simulated if source_kind == "demo" else Origin.real
    now = clock()
    try:
        return await _run(
            db,
            state,
            lambda c: service.propose(
                c,
                household_id=household_id,
                resident_id=access.resident_id,
                body=body,
                plugs=plugs,
                origin=origin,
                now=now,
            ),
        )
    except ValidationError:  # gatilho incoerente (ex.: `power_above` sem limiar)
        raise HTTPException(
            400, {"code": "invalid_request", "message": "Pedido inválido (trigger)"}
        ) from None


@router.post("/households/{household_id}/automations/{automation_id}/vote")
async def vote_automation(
    automation_id: UUID,
    body: AutomationVoteIn,
    access: WriteAccess,
    db: DbDep,
    clock: ClockDep,
    state: StateDep,
) -> AutomationView:
    now = clock()
    return await _run(
        db,
        state,
        lambda c: service.vote(
            c, access.household_id, access.resident_id, automation_id, body.approve, now
        ),
    )


@router.patch("/households/{household_id}/automations/{automation_id}")
async def suspend_automation(
    automation_id: UUID,
    body: AutomationStatusIn,
    access: WriteAccess,
    db: DbDep,
    clock: ClockDep,
    state: StateDep,
) -> AutomationView:
    """Suspende (`active → disabled`) na hora; qualquer inquilino da casa o pode fazer."""
    now = clock()
    return await _run(
        db,
        state,
        lambda c: service.suspend(c, access.household_id, access.resident_id, automation_id, now),
    )


@router.post("/households/{household_id}/automations/{automation_id}/reactivate")
async def reactivate_automation(
    automation_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> AutomationView:
    """Abre uma nova votação para reativar uma regra suspensa; só a maioria a torna `active`."""
    now = clock()
    return await _run(
        db,
        state,
        lambda c: service.reactivate(
            c, access.household_id, access.resident_id, automation_id, now
        ),
    )
