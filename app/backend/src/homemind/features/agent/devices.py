"""Dispositivos que o assistente pode propor comandar (só atuadores: tomada e lâmpada).

`DeviceDirectory` é a porta; a feature não conhece o MCP nem o `Home`. Hoje só há dispositivos
SIMULADOS, na casa de demonstração (`DemoDevices`); as outras casas não têm nenhum (`NoDevices`).
PROPOSTA para a P1: registar um diretório real em `app.state.agent_device_directory` (ver
`select_directory`); sem ele, uma casa real continua sem dispositivos e o agente recusa.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from homemind.contracts import fixtures as fx
from homemind.contracts.devices import DeviceKind

DIRECTORY_ATTR = "agent_device_directory"

__all__ = [
    "DIRECTORY_ATTR",
    "ActuatorDevice",
    "DemoDevices",
    "DeviceDirectory",
    "NoDevices",
    "select_directory",
]


@dataclass(frozen=True)
class ActuatorDevice:
    id: UUID  # interno; o id do MCP resolve-se no conector, nunca aqui
    name: str
    kind: DeviceKind  # plug | bulb
    simulated: bool
    # Tomada que alimenta vários aparelhos (a extensão): desligá-la corta tudo o que lá está.
    aggregate: bool = False


class DeviceDirectory(Protocol):
    def actuators(self, household_id: UUID) -> list[ActuatorDevice]: ...


class NoDevices:
    def actuators(self, household_id: UUID) -> list[ActuatorDevice]:
        return []


class DemoDevices:
    """SIMULADO: a tomada da extensão e a lâmpada da sala da casa de demonstração."""

    def actuators(self, household_id: UUID) -> list[ActuatorDevice]:
        if household_id != fx.HOUSEHOLD:
            return []
        meter = fx.meter()
        return [
            ActuatorDevice(meter.id, meter.name, DeviceKind.plug, simulated=True, aggregate=True),
            # As fixtures só têm o id da lâmpada (`fx.LAMP`), não um `Device`.
            ActuatorDevice(fx.LAMP, "Lâmpada da sala", DeviceKind.bulb, simulated=True),
        ]


_NONE = NoDevices()
_DEMO = DemoDevices()


def select_directory(state, household_id: UUID, source_kind: str) -> DeviceDirectory:
    """Casa de demonstração: sempre os dispositivos SIMULADOS. Casa real: o diretório registado
    pela P1 em `app.state`, ou nenhum dispositivo."""
    if source_kind == "demo":
        return _DEMO if household_id == fx.HOUSEHOLD else _NONE
    return getattr(state, DIRECTORY_ATTR, None) or _NONE
