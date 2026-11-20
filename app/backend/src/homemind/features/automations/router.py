"""Regras da casa votadas por todos e regras individuais (SAFE-04): propor, listar, votar,
suspender e reativar. Uma regra individual (`scope=personal`) é privada do dono: para os outros
moradores não existe (404 e fora das listas).

Só inquilinos (`Resource.automation`): o senhorio e o operador recebem 403 e quem não é membro da
casa, 404 (padrão de `core/access.py`). O residente vem sempre do token; uma regra de outra casa
é 404. Nenhuma rota executa nada (o motor, `runner.py`, liga-se ao barramento no lifespan). A
resposta é a `AutomationView` (só contagens, nunca quem votou o quê). Os eventos já estão no
outbox; depois do COMMIT acorda-se o barramento (uma falha só atrasa a entrega).
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
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
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.devices import select_directory
from homemind.features.automations import repo, service
from homemind.features.automations.engine import AutomationEngine
from homemind.features.automations.runner import AutomationRunner
from homemind.features.automations.service import (
    AutomationPlugView,
    AutomationProposeIn,
    AutomationStatusIn,
    AutomationView,
    AutomationVoteIn,
    ConflictError,
    Result,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Liga o motor ao barramento (só desliga tomadas; casa de demonstração = só o simulado)."""
    settings = get_agent_settings()
    runner = AutomationRunner(
        app.state,
        clock=lambda: datetime.now(UTC),
        engine=AutomationEngine(
            device_cooldown_s=settings.agent_action_cooldown_s,
            lockout_s=settings.agent_action_lockout_s,
        ),
        timeout_s=settings.agent_action_timeout_s,
    )
    runner.attach(app.state.bus)
    app.state.automations_runner = runner
    log.info("automations: motor subscrito (executor simulado na demo; real só com a P1/MCP-04)")
    try:
        yield
    finally:
        await runner.close()


router = APIRouter(prefix="/api", tags=["automations"], lifespan=lifespan)

ReadAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.automation, Operation.read))
]
WriteAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.automation, Operation.write))
]

_ERRORS = {
    service.NOT_FOUND: (404, "Regra não encontrada"),
    service.NOT_ELIGIBLE: (403, "Só os inquilinos da casa participam nesta votação"),
    service.INVALID_TARGET: (
        400,
        "A regra só pode usar uma tomada conhecida da casa (numa regra individual, do teu quarto)",
    ),
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


async def _known_plugs(
    db: Database, state: State, household_id: UUID, resident_id: UUID, now: datetime
) -> list[AutomationPlugView]:
    """Tomadas que o servidor aceita como gatilho/alvo (a mesma fonte da validação de `propose`).
    Casa de demonstração: as do diretório simulado e as tomadas SIMULADAS do catálogo da casa (a
    tomada viva da demo web tem outro id que a do cenário offline). Casa real: só as reais.
    `room_id` vem do diretório ou, na falta, do catálogo `device`; `personal_allowed` marca as
    tomadas do quarto de quem pede (regra individual)."""
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()
    )
    source_kind = row["source_kind"]
    devices = select_directory(state, household_id, source_kind).actuators(household_id)
    if source_kind != "demo":  # uma casa real nunca usa dispositivos simulados
        devices = [d for d in devices if not d.simulated]
    catalog_rooms = await db.run(
        lambda c: {
            UUID(r["id"]): UUID(r["room_id"]) if r["room_id"] else None
            for r in c.execute(
                "SELECT id, room_id FROM device WHERE household_id = ? AND kind = 'plug'",
                (str(household_id),),
            )
        }
    )
    my_room = await db.run(lambda c: repo.tenant_room(c, household_id, resident_id, now))
    plugs = {
        d.id: (d.name, d.simulated, d.room_id or catalog_rooms.get(d.id))
        for d in devices
        if d.kind is DeviceKind.plug
    }
    if source_kind == "demo":
        rows = await db.run(
            lambda c: c.execute(
                "SELECT id, name FROM device WHERE household_id = ? AND kind = 'plug'"
                " AND source = 'fake'",
                (str(household_id),),
            ).fetchall()
        )
        for r in rows:
            plugs.setdefault(UUID(r["id"]), (r["name"], True, catalog_rooms.get(UUID(r["id"]))))
    return [
        AutomationPlugView(
            id=i, name=n, simulated=sim, room_id=room,
            personal_allowed=room is not None and room == my_room,
        )
        for i, (n, sim, room) in sorted(plugs.items(), key=lambda kv: (kv[1][0], str(kv[0])))
    ]  # fmt: skip


@router.get("/households/{household_id}/automations/plugs")
async def list_automation_plugs(
    access: ReadAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> list[AutomationPlugView]:
    """As tomadas que a casa pode usar numa regra (o que o servidor aceitaria em `POST`).
    `personal_allowed` diz quais servem numa regra individual de quem pede (as do seu quarto)."""
    return await _known_plugs(db, state, access.household_id, access.resident_id, clock())


@router.get("/households/{household_id}/automations")
async def list_automations(
    access: ReadAccess,
    db: DbDep,
    clock: ClockDep,
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AutomationView]:
    """As regras da casa e as individuais de quem pede (nunca as dos outros), da mais recente à
    mais antiga. Uma votação fora de prazo resolve-se
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
    """Propõe uma regra da casa: fica `proposed`, por votar (todos os moradores têm de aprovar), e
    nada é executado. O alvo tem de ser uma tomada conhecida da casa (a lâmpada nunca). Com
    `scope=personal` cria uma regra individual: `active` na hora, privada, só em tomadas do
    quarto do próprio (`400 invalid_target` nas restantes)."""
    household_id = access.household_id
    now = clock()
    known = await _known_plugs(db, state, household_id, access.resident_id, now)
    plugs = {p.id: p.name for p in known}
    plug_rooms = {p.id: p.room_id for p in known}
    origin = Origin.simulated if any(p.simulated for p in known) else Origin.real
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
                plug_rooms=plug_rooms,
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
    """Suspende (`active → disabled`) na hora; qualquer inquilino da casa o pode fazer numa regra
    da casa (veto); uma individual só o dono."""
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
    """Abre uma nova votação para reativar uma regra da casa suspensa (só a unanimidade a torna
    `active`); uma individual suspensa o dono reativa-a na hora, sem votação."""
    now = clock()
    return await _run(
        db,
        state,
        lambda c: service.reactivate(
            c, access.household_id, access.resident_id, automation_id, now
        ),
    )
