"""Fakes das ações propostas: executor com comportamento escolhido e diretório de dispositivos.

Nada aqui toca em hardware, rede ou MCP: o `FakeExecutor` só regista as chamadas.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from homemind.contracts.agent import (
    ActionConfirmation,
    ActionExecutionResult,
    ExecutionStatus,
    ProposedAction,
)
from homemind.contracts.common import stable_id
from homemind.contracts.devices import DeviceKind
from homemind.features.agent.devices import ActuatorDevice

REAL_PLUG = ActuatorDevice(
    stable_id("device", "c-plug"), "Tomada do corredor", DeviceKind.plug, False
)
REAL_BULB = ActuatorDevice(
    stable_id("device", "c-bulb"), "Candeeiro da sala", DeviceKind.bulb, False
)


class FakeDirectory:
    def __init__(self, devices: list[ActuatorDevice]):
        self.devices = devices

    def actuators(self, household_id: UUID) -> list[ActuatorDevice]:
        return list(self.devices)


class FakeExecutor:
    """`behaviour`: confirmed | failed | uncertain | raise | wrong_id | hang."""

    def __init__(self, clock: Callable[[], datetime], behaviour: str = "confirmed"):
        self.clock = clock
        self.behaviour = behaviour
        self.calls: list[tuple[ProposedAction, ActionConfirmation]] = []
        self.on_call: Callable[[], None] | None = None  # observa o estado no momento da chamada

    async def execute(
        self, action: ProposedAction, confirmation: ActionConfirmation
    ) -> ActionExecutionResult:
        self.calls.append((action, confirmation))
        if self.on_call:
            self.on_call()
        at = self.clock()
        match self.behaviour:
            case "raise":
                raise RuntimeError("Bearer segredo-xyz")
            case "hang":
                await asyncio.sleep(60)
            case "failed":
                return ActionExecutionResult(
                    action_id=action.id, status=ExecutionStatus.failed, mcp_is_error=True,
                    executed_at=at, code="mcp_error",
                )  # fmt: skip
            case "uncertain":
                return ActionExecutionResult(
                    action_id=action.id, status=ExecutionStatus.uncertain, mcp_is_error=False,
                    executed_at=at, code="no_readback",
                )  # fmt: skip
            case "wrong_id":
                return ActionExecutionResult(
                    action_id=stable_id("outra"), status=ExecutionStatus.confirmed,
                    readback_confirmed=True, executed_at=at,
                )  # fmt: skip
        return ActionExecutionResult(
            action_id=action.id, status=ExecutionStatus.confirmed, mcp_is_error=False,
            readback_confirmed=True, executed_at=at,
        )  # fmt: skip
