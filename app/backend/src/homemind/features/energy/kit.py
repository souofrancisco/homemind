"""Liga o kit MCP ao catálogo e ao barramento, sem divulgar referências externas."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from homemind.connectors.mcp_collector import EnergyCollector
from homemind.connectors.mcp_home import McpHome
from homemind.connectors.mcp_sensor_collector import SensorBinding, SensorCollector
from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import Origin, new_id
from homemind.contracts.devices import Device, DeviceKind, DeviceRole, DeviceSource, PowerUnit
from homemind.contracts.home import EstadoCasa, Home
from homemind.contracts.sensors import SensorReading
from homemind.core.config import Settings
from homemind.core.db import Database
from homemind.core.events import EventBus
from homemind.features.energy.kit_actuators import lamp_device_id
from homemind.features.energy.lamp import LampEstimator
from homemind.features.energy.locate import locate

log = logging.getLogger(__name__)


class _Registration:
    def __init__(self, household_id: UUID, db: Database, catalog: ApplianceCatalog) -> None:
        self.household_id = household_id
        self.db = db
        self.catalog = catalog

    def register(self, external_ref: str, kind: DeviceKind, unit: PowerUnit) -> UUID:
        device = Device(
            id=new_id(),
            household_id=self.household_id,
            name="Tomada do kit" if kind is DeviceKind.plug else "Sensor do kit",
            kind=kind,
            role=DeviceRole.main_meter if kind is DeviceKind.plug else DeviceRole.none,
            source=DeviceSource.mcp,
            external_ref=external_ref,
            power_unit=unit,
        )
        return self.db.run_sync(lambda conn: self.catalog.register_device(conn, device)).id


class _LazyEnergy:
    def __init__(self, registration, bus, unit, clock) -> None:
        self._registration = registration
        self._bus = bus
        self._unit = unit
        self._clock = clock
        self._collectors: dict[str, EnergyCollector] = {}

    def ingest(self, device: dict[str, Any] | None):
        if not isinstance(device, dict) or not isinstance(device.get("id"), str):
            return None
        ref = device["id"]
        if ref not in self._collectors:
            try:
                device_id = self._registration.register(ref, DeviceKind.plug, self._unit)
                self._collectors[ref] = EnergyCollector(
                    household_id=self._registration.household_id,
                    device_id=device_id,
                    unit=self._unit,
                    publish=self._bus.publish_threadsafe,
                    origin=Origin.real,
                    clock=self._clock,
                )
            except Exception as exc:
                log.warning("Registo do kit falhou (%s)", type(exc).__name__)
                return None
        return self._collectors[ref].ingest(device)

    def unavailable(self) -> None:
        for collector in self._collectors.values():
            collector.unavailable()


class _LazySensors:
    def __init__(self, registration, bus, clock) -> None:
        self._registration = registration
        self._bus = bus
        self._clock = clock
        self._collectors: dict[str, SensorCollector] = {}

    def ingest(self, devices: Any) -> list[SensorReading]:
        if not isinstance(devices, list):
            return []
        result = []
        for device in devices:
            if (
                not isinstance(device, dict)
                or not isinstance(device.get("id"), str)
                or device.get("type") not in ("contactSensor", "temperatureSensor")
            ):
                continue
            ref = device["id"]
            if ref not in self._collectors:
                try:
                    device_id = self._registration.register(
                        ref, DeviceKind.sensor, PowerUnit.unknown
                    )
                    self._collectors[ref] = SensorCollector(
                        household_id=self._registration.household_id,
                        bindings={ref: SensorBinding(device_id=device_id, room_id=None)},
                        publish=self._bus.publish_threadsafe,
                        origin=Origin.real,
                        clock=self._clock,
                    )
                except Exception as exc:
                    log.warning("Registo do kit falhou (%s)", type(exc).__name__)
                    continue
            result.extend(self._collectors[ref].ingest([device]))
        return result

    def unavailable(self) -> None:
        for collector in self._collectors.values():
            collector.unavailable()


def _attach_lamp(
    home: McpHome,
    registration: _Registration,
    bus: EventBus,
    room_id: UUID | None,
) -> None:
    """Estimativa da lâmpada (9 W × tempo × brilho) a partir do estado que o `McpHome` já lê.
    A lâmpada só se regista no catálogo quando liga pela primeira vez."""

    def register() -> UUID:
        ref = home.lamp_ref
        if ref is None:
            raise ValueError("lâmpada ainda não descoberta")
        device = Device(
            id=lamp_device_id(ref),
            household_id=registration.household_id,
            room_id=room_id,
            name="Lâmpada do kit",
            kind=DeviceKind.bulb,
            source=DeviceSource.mcp,
            external_ref=ref,
        )
        return registration.db.run_sync(
            lambda c: registration.catalog.register_device(c, device)
        ).id

    def where(device_id: UUID):
        return locate(
            registration.db.run_sync(
                lambda c: registration.catalog.device_location(
                    c, registration.household_id, device_id
                )
            )
        )

    estimator = LampEstimator(
        registration.household_id, register=register, locate=where, publish=bus.publish_threadsafe
    )
    previous = home.ao_estado

    def listen(casa: EstadoCasa, mudou: bool) -> None:
        if previous is not None:
            previous(casa, mudou)
        lamp = casa.lampada
        origin = Origin.simulated if casa.backend == "fake" else Origin.real
        try:
            estimator.observe(lamp.ligada, lamp.brilho, casa.atualizado_em, origin)
        except Exception as exc:  # nunca derruba o polling
            log.warning("Estimativa da lâmpada falhou (%s)", type(exc).__name__)

    home.ao_estado = listen


async def attach_kit_collectors(
    home: Home,
    *,
    settings: Settings,
    db: Database,
    bus: EventBus,
    catalog: ApplianceCatalog | None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Só ativa na casa configurada; a descoberta/registo ocorre nas próximas leituras."""
    if not isinstance(home, McpHome) or settings.home_backend != "mcp":
        return
    if catalog is None:
        log.warning("Collectors do kit desligados: catálogo de aparelhos indisponível")
        return
    household_id = settings.energy_household_id
    if household_id is None:
        log.warning("Collectors do kit desligados: casa não configurada")
        return
    exists = await db.run(
        lambda conn: conn.execute(
            "SELECT 1 FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()
        is not None
    )
    if not exists:
        log.warning("Collectors do kit desligados: casa inexistente")
        return
    registration = _Registration(household_id, db, catalog)
    unit = PowerUnit(settings.mcp_instantpower_unit or PowerUnit.unknown)
    home.coletor = _LazyEnergy(registration, bus, unit, clock)
    home.sensores = _LazySensors(registration, bus, clock)
    _attach_lamp(home, registration, bus, settings.mcp_lamp_room_id)
