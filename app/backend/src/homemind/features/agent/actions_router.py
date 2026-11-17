"""Ações propostas pelo assistente: listar, ver, confirmar e rejeitar (AGENT-03).

Montado por `router.py` (`router.include_router`). Só inquilinos (`Resource.agent`); o residente
vem sempre do token e só vê e decide as ações que lhe foram propostas (a de outro é 404). A
execução só acontece em `POST …/confirm`, depois do COMMIT da confirmação, uma única vez, por um
`ActionExecutor` injetado (nesta feature só o simulado). Nunca há sucesso sem releitura.
"""

import logging
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.datastructures import State

from homemind.contracts.agent import (
    ActionExecutionResult,
    ActionStatus,
    AgentResponse,
    ExecutionStatus,
)
from homemind.contracts.common import Origin
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.core.db import Database
from homemind.features.agent import actions
from homemind.features.agent.actions import ActionLimits, AgentActionView
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.devices import select_directory
from homemind.features.agent.execution import run_execution, select_executor
from homemind.features.agent.intents import Refusal, parse_action

log = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

ReadAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.agent, Operation.read))]
WriteAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.agent, Operation.write))]

TOO_MANY_OPEN = (
    "Já tens propostas por confirmar a mais. Confirma ou rejeita algumas antes de pedires outra."
)


def get_state(request: Request) -> State:
    return request.app.state


StateDep = Annotated[State, Depends(get_state)]


def _error(code: str) -> HTTPException:
    status, message = {
        actions.NOT_FOUND: (404, "Ação não encontrada"),
        actions.NOT_PENDING: (409, "A ação já não está pendente"),
        actions.EXPIRED: (409, "A proposta expirou"),
    }[code]
    return HTTPException(status, {"code": code, "message": message})


async def _source_kind(db: Database, household_id: UUID) -> str:
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()
    )
    return row["source_kind"]


async def _wake(state: State, event) -> None:
    """Depois do COMMIT: acorda os consumidores. O evento já está no outbox, por isso uma falha
    aqui só atrasa a entrega e nunca falha o pedido."""
    try:
        await state.bus.publish(event)
    except Exception as e:  # noqa: BLE001 - só o tipo vai para o log
        log.warning("falha a publicar %s (%s)", event.type, type(e).__name__)


async def reply_to_action_request(
    state: State, db: Database, access: HouseholdAccess, text: str, now
) -> AgentResponse:
    """Pedido de ação no chat → proposta (nunca execução) ou texto de recusa. Determinístico:
    o LLM não participa. A ação fica por confirmar em `proposed_actions`."""
    household_id = access.household_id
    source_kind = await _source_kind(db, household_id)
    devices = select_directory(state, household_id, source_kind).actuators(household_id)
    if source_kind != "demo":  # uma casa real nunca comanda dispositivos simulados
        devices = [d for d in devices if not d.simulated]
    parsed = parse_action(text, devices)

    def response(body: str, proposed: list | None = None) -> AgentResponse:
        return AgentResponse(
            id=uuid4(),
            household_id=household_id,
            text=body,
            proposed_actions=proposed or [],
            created_at=now,
        )

    if isinstance(parsed, Refusal):
        return response(parsed.text)
    limits = ActionLimits.from_settings(get_agent_settings())
    origin = Origin.simulated if source_kind == "demo" else Origin.real
    made = await db.run(
        lambda c: actions.propose(
            c,
            household_id=household_id,
            resident_id=access.resident_id,
            device=parsed.device,
            command=parsed.command,
            rationale=parsed.rationale,
            origin=origin,
            now=now,
            limits=limits,
        )
    )
    if made is None:
        return response(TOO_MANY_OPEN)
    view, event = made
    await _wake(state, event)
    return response(
        f"{parsed.rationale} Ainda não foi executado: precisa da tua confirmação (confirma ou "
        "rejeita a ação proposta).",
        [view.action],
    )


def _record_interrupted(
    db: Database,
    household_id: UUID,
    resident_id: UUID,
    action_id: UUID,
    result: ActionExecutionResult | None,
    now,
) -> None:
    """Execução interrompida (cancelamento, erro inesperado) depois do COMMIT da confirmação:
    grava já o desfecho, de forma SÍNCRONA (um `await` aqui seria cancelado outra vez). Sem
    resultado conhecido é `uncertain/interrupted`: pode ter sido aplicado, por isso nunca se
    repete e o dispositivo fica bloqueado. É um CAS: se o desfecho já entrou, não faz nada."""
    outcome = result or ActionExecutionResult(
        action_id=action_id, status=ExecutionStatus.uncertain, executed_at=now,
        code=actions.INTERRUPTED,
    )  # fmt: skip
    try:
        db.run_sync(
            lambda c: actions.record_execution(
                c, household_id, resident_id, action_id, outcome, now
            )
        )
        log.warning("Execução da ação %s interrompida; desfecho registado", action_id)
    except Exception as e:  # noqa: BLE001 - o `sweep_stale` resolve-a mais tarde
        log.error("Não consegui registar a execução interrompida (%s)", type(e).__name__)


@router.get("/households/{household_id}/agent/actions")
async def list_actions(
    access: ReadAccess,
    db: DbDep,
    clock: ClockDep,
    status: ActionStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AgentActionView]:
    """As ações propostas ao residente (as suas), da mais recente à mais antiga."""
    now = clock()
    stale_s = ActionLimits.from_settings(get_agent_settings()).stale_s

    def read(c):
        actions.sweep_stale(c, access.household_id, now, stale_s)  # interrompidas → incertas
        return actions.list_views(c, access.household_id, access.resident_id, now, status, limit)

    return await db.run(read)


@router.get("/households/{household_id}/agent/actions/{action_id}")
async def get_action(
    action_id: UUID, access: ReadAccess, db: DbDep, clock: ClockDep
) -> AgentActionView:
    now = clock()
    stale_s = ActionLimits.from_settings(get_agent_settings()).stale_s

    def read(c):
        actions.sweep_stale(c, access.household_id, now, stale_s)  # interrompidas → incertas
        return actions.get_view(c, access.household_id, access.resident_id, action_id, now)

    view = await db.run(read)
    if view is None:
        raise _error(actions.NOT_FOUND)
    return view


@router.post("/households/{household_id}/agent/actions/{action_id}/confirm")
async def confirm_action(
    action_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep, state: StateDep
) -> AgentActionView:
    """Confirmação humana. `proposed → confirmed` faz COMMIT antes de chamar o executor; este
    corre no máximo uma vez. Sem executor, limite violado ou resultado incerto: nada se repete e
    a resposta diz o que aconteceu (nunca sucesso sem releitura)."""
    settings = get_agent_settings()
    limits = ActionLimits.from_settings(settings)
    household_id, resident_id = access.household_id, access.resident_id
    now = clock()
    out = await db.run(
        lambda c: actions.confirm(c, household_id, resident_id, action_id, now, limits)
    )
    if out.error:
        raise _error(out.error)
    if out.pending is None:  # bloqueada por um limite: nada a executar
        assert out.view is not None
        return out.view
    action, confirmation = out.pending
    executor = select_executor(state, household_id, await _source_kind(db, household_id), clock)
    result: ActionExecutionResult | None = None
    try:
        result = await run_execution(
            executor, action, confirmation, timeout_s=settings.agent_action_timeout_s, clock=clock
        )
        view = await db.run(
            lambda c: actions.record_execution(
                c, household_id, resident_id, action.id, result, clock()
            )
            or actions.get_view(c, household_id, resident_id, action.id, clock())
        )
    except BaseException:  # incl. CancelledError: o executor pode ter aplicado a ação
        _record_interrupted(db, household_id, resident_id, action.id, result, clock())
        raise
    assert view is not None
    return view


@router.post("/households/{household_id}/agent/actions/{action_id}/reject")
async def reject_action(
    action_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep
) -> AgentActionView:
    now = clock()
    view, error = await db.run(
        lambda c: actions.reject(c, access.household_id, access.resident_id, action_id, now)
    )
    if error:
        raise _error(error)
    assert view is not None
    return view
