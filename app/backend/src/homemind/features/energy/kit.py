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
from homemind.contracts.home import Home
from homemind.contracts.sensors import SensorReading
from homemind.core.config import Settings
from homemind.core.db import Database
from homemind.core.events import EventBus

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


async def attach_kit_collectors(
    home: Home,
    *,
    settings: Settings,
    db: Database,
    bus: EventBus,
    catalog: ApplianceCatalog,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Só ativa na casa configurada; a descoberta/registo ocorre nas próximas leituras."""
    if not isinstance(home, McpHome) or settings.home_backend != "mcp":
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
