"""Execução de uma ação JÁ confirmada. Esta feature nunca toca em dispositivos nem no MCP.

`ActionExecutor` é a porta (PROPOSTA para a P1: registar uma implementação em
`app.state.agent_action_executor`, que aplica flag + grant + whitelist, escreve e RELÊ). Aqui só
há o `SimulatedExecutor` (estado em memória, a casa de demonstração) e `run_execution`, que
chama o executor uma única vez e traduz qualquer falha em resultados honestos:

- sem executor → `blocked` (`executor_unavailable`): nada foi tentado;
- prazo esgotado, exceção ou resultado inválido → `uncertain`: pode ter sido aplicado, por isso
  NUNCA se repete (`may_retry` é falso) e fica bloqueado o dispositivo (ver `actions.py`).
Sucesso físico só existe com releitura (`ActionExecutionResult` recusa `confirmed` sem ela).
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from homemind.contracts.agent import (
    ActionConfirmation,
    ActionExecutionResult,
    DeviceCapability,
    ExecutionStatus,
    ProposedAction,
)

log = logging.getLogger(__name__)

EXECUTOR_ATTR = "agent_action_executor"
_SIMULATED_ATTR = "agent_simulated_executor"

__all__ = [
    "EXECUTOR_ATTR",
    "ActionExecutor",
    "SimulatedExecutor",
    "run_execution",
    "select_executor",
]


class ActionExecutor(Protocol):
    async def execute(
        self, action: ProposedAction, confirmation: ActionConfirmation
    ) -> ActionExecutionResult:
        """Aplica UMA vez e devolve o desfecho. `confirmed` só com releitura do estado."""
        ...


class SimulatedExecutor:
    """SIMULADO: aplica o comando a um estado em memória e relê-o; não toca em nada real."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._state: dict[UUID, dict[str, object]] = {}

    def read(self, device_id: UUID) -> dict[str, object]:
        return dict(self._state.get(device_id, {}))

    async def execute(
        self, action: ProposedAction, confirmation: ActionConfirmation
    ) -> ActionExecutionResult:
        now = self._clock()
        # Defesa em profundidade: sem confirmação humana desta ação, nada se aplica.
        if not confirmation.accepted or confirmation.action_id != action.id:
            return ActionExecutionResult(
                action_id=action.id, status=ExecutionStatus.blocked, executed_at=now,
                code="not_confirmed",
            )  # fmt: skip
        cmd = action.command
        wanted: object = {
            DeviceCapability.power: cmd.power,
            DeviceCapability.brightness: cmd.brightness,
            DeviceCapability.color_rgb: cmd.color_rgb,
        }[cmd.capability]
        self._state.setdefault(cmd.target_device_id, {})[cmd.capability.value] = wanted
        confirmed = self.read(cmd.target_device_id).get(cmd.capability.value) == wanted
        return ActionExecutionResult(
            action_id=action.id,
            status=ExecutionStatus.confirmed if confirmed else ExecutionStatus.uncertain,
            readback_confirmed=confirmed,
            executed_at=self._clock(),
            code=None if confirmed else "readback_mismatch",
        )


def select_executor(
    state, household_id: UUID, source_kind: str, clock: Callable[[], datetime]
) -> ActionExecutor | None:
    """Casa de demonstração: SEMPRE o simulado (nunca hardware, mesmo que haja um executor
    registado). Casa real: o executor registado pela P1, ou `None` (→ `executor_unavailable`)."""
    if source_kind == "demo":
        sim = getattr(state, _SIMULATED_ATTR, None)
        if sim is None:
            sim = SimulatedExecutor(clock)
            setattr(state, _SIMULATED_ATTR, sim)
        return sim
    return getattr(state, EXECUTOR_ATTR, None)


async def run_execution(
    executor: ActionExecutor | None,
    action: ProposedAction,
    confirmation: ActionConfirmation,
    *,
    timeout_s: float,
    clock: Callable[[], datetime],
) -> ActionExecutionResult:
    """Chama o executor no máximo uma vez. Nunca repete e nunca levanta (salvo cancelamento)."""

    def result(status: ExecutionStatus, code: str) -> ActionExecutionResult:
        return ActionExecutionResult(
            action_id=action.id, status=status, executed_at=clock(), code=code
        )

    if executor is None:
        return result(ExecutionStatus.blocked, "executor_unavailable")
    try:
        async with asyncio.timeout(timeout_s):
            outcome = await executor.execute(action, confirmation)
    except TimeoutError:
        log.warning("Executor sem resposta a tempo; resultado incerto")
        return result(ExecutionStatus.uncertain, "timeout")
    except Exception as e:  # noqa: BLE001 - só o tipo vai para o log; o efeito é desconhecido
        log.warning("Executor falhou (%s); resultado incerto", type(e).__name__)
        return result(ExecutionStatus.uncertain, "executor_error")
    try:  # revalida: um resultado construído sem validação não passa por sucesso
        if not isinstance(outcome, ActionExecutionResult):
            raise TypeError
        checked = ActionExecutionResult.model_validate(outcome.model_dump())
        if checked.action_id != action.id:
            raise ValueError
    except (TypeError, ValueError):
        log.warning("Executor devolveu um resultado inválido; resultado incerto")
        return result(ExecutionStatus.uncertain, "invalid_result")
    return checked
