"""Lâmpada REAL do kit para as ações confirmadas do assistente (ALERT-06, AGENT-03b).

Implementa as duas portas que o `agent` deixou para a P1 (ver `features/agent/execution.py` e
`devices.py`), registadas em `app.state` pelo arranque do engine, onde vive o `McpHome`:

- `KitLampDirectory`: a lâmpada do kit como atuador, só na casa `ENERGY_HOUSEHOLD_ID` e só depois
  de o MCP a ter descoberto. O id interno é derivado do id MCP (`stable_id`), que nunca sai daqui.
  A divisão vem de `MCP_LAMP_ROOM_ID`; sem ela a lâmpada fica com divisão desconhecida e a cor do
  orçamento nunca lhe é proposta.
- `KitLampExecutor`: aplica UMA vez um comando já confirmado, pelo caminho de escrita existente
  do `McpHome` (flag `ENABLE_PHYSICAL_WRITES`, grant temporário MCP-04, whitelist e releitura).
  Sucesso só com releitura. Recusado pelas guardas → `blocked`; o MCP devolveu erro → `failed`;
  qualquer outra falha depois de tentar → `uncertain` (pode ter sido aplicado: nunca se repete).

Só lâmpada: a tomada do kit é o contador geral (`main_meter`), não um atuador do assistente.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from homemind.connectors.mcp_home import McpHome
from homemind.connectors.write_policy import WriteOutcome
from homemind.contracts.agent import (
    ActionConfirmation,
    ActionExecutionResult,
    DeviceCapability,
    ExecutionStatus,
    ProposedAction,
    RgbColor,
)
from homemind.contracts.common import stable_id
from homemind.contracts.devices import DeviceKind
from homemind.contracts.home import CORES

_MCP_REFUSED = "MCP recusou a alteração"  # `McpHome._escrever` quando `isError=true`


@dataclass(frozen=True)
class KitActuator:
    """Mesma forma que `agent.devices.ActuatorDevice` (protocolo estrutural; sem importar)."""

    id: UUID
    name: str
    kind: DeviceKind
    simulated: bool = False
    aggregate: bool = False
    room_id: UUID | None = None


def lamp_device_id(ref: str) -> UUID:
    return stable_id("device", "mcp-lamp", ref)


class KitLampDirectory:
    def __init__(self, home: McpHome, household_id: UUID, room_id: UUID | None) -> None:
        self._home, self._household_id, self._room_id = home, household_id, room_id

    def actuators(self, household_id: UUID) -> list[KitActuator]:
        ref = self._home.lamp_ref
        if household_id != self._household_id or ref is None:
            return []
        return [
            KitActuator(
                lamp_device_id(ref), "Lâmpada do kit", DeviceKind.bulb, room_id=self._room_id
            )
        ]


def _color_name(rgb: RgbColor) -> str | None:
    """Só as cores do vocabulário MCP (`CORES`): uma cor arbitrária não se envia."""
    return next((name for name, value in CORES.items() if value == (rgb.r, rgb.g, rgb.b)), None)


class KitLampExecutor:
    def __init__(self, home: McpHome, clock: Callable[[], datetime]) -> None:
        self._home, self._clock = home, clock

    def _result(
        self, action: ProposedAction, status: ExecutionStatus, code: str | None = None, **kw
    ) -> ActionExecutionResult:
        return ActionExecutionResult(
            action_id=action.id, status=status, executed_at=self._clock(), code=code, **kw
        )

    async def execute(
        self, action: ProposedAction, confirmation: ActionConfirmation
    ) -> ActionExecutionResult:
        blocked = ExecutionStatus.blocked
        # Defesa em profundidade: sem confirmação humana desta ação, nada se aplica.
        if not confirmation.accepted or confirmation.action_id != action.id:
            return self._result(action, blocked, "not_confirmed")
        ref = self._home.lamp_ref
        cmd = action.command
        if ref is None or cmd.target_device_id != lamp_device_id(ref):
            return self._result(action, blocked, "unknown_device")
        if cmd.capability is DeviceCapability.power:
            ok = await self._home.definir_lampada(bool(cmd.power))
        elif cmd.capability is DeviceCapability.brightness:
            if not cmd.brightness:  # 0 % = desligar: pede-se `power`, não brilho
                return self._result(action, blocked, "invalid_brightness")
            ok = await self._home.definir_lampada(True, brilho=cmd.brightness)
        else:
            assert cmd.color_rgb is not None
            name = _color_name(cmd.color_rgb)
            if name is None:
                return self._result(action, blocked, "color_not_supported")
            ok = await self._home.definir_lampada(True, cor=name)
        if ok:
            return self._result(action, ExecutionStatus.confirmed, readback_confirmed=True)
        outcome = self._home.ultimo_resultado
        if outcome is not None and outcome.outcome is WriteOutcome.refused:
            return self._result(action, blocked, "write_refused")  # flag/grant/whitelist
        if outcome is not None and outcome.reason == _MCP_REFUSED:
            return self._result(action, ExecutionStatus.failed, "mcp_error", mcp_is_error=True)
        return self._result(action, ExecutionStatus.uncertain, "not_confirmed_by_readback")


EXECUTOR_ATTR = "agent_action_executor"  # = `agent.execution.EXECUTOR_ATTR`
DIRECTORY_ATTR = "agent_device_directory"  # = `agent.devices.DIRECTORY_ATTR`


def attach_kit_actuators(state, home, *, settings, clock: Callable[[], datetime]) -> bool:
    """Regista a lâmpada do kit nas portas do agente, só com `HOME_BACKEND=mcp` e casa
    configurada. Não escreve nada: as guardas de escrita física continuam no `McpHome`."""
    if not isinstance(home, McpHome) or settings.home_backend != "mcp":
        return False
    if settings.energy_household_id is None:
        return False
    setattr(
        state,
        DIRECTORY_ATTR,
        KitLampDirectory(home, settings.energy_household_id, settings.mcp_lamp_room_id),
    )
    setattr(state, EXECUTOR_ATTR, KitLampExecutor(home, clock))
    return True
