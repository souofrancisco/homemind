from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from homemind.connectors.mcp_sensors import sensor_readings_from_device
from homemind.contracts.common import Origin
from homemind.contracts.domain_events import SensorReadingRecorded
from homemind.contracts.sensors import SensorKind, SensorReading

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensorBinding:
    device_id: UUID
    room_id: UUID | None = None


class SensorCollector:
    def __init__(
        self,
        *,
        household_id: UUID,
        bindings: Mapping[str, SensorBinding],
        publish: Callable[[SensorReadingRecorded], object],
        stale_after: Mapping[SensorKind, timedelta] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        origin: Origin = Origin.real,
    ) -> None:
        self._household_id = household_id
        self._bindings = bindings
        self._publish = publish
        self._stale_after = stale_after
        self._clock = clock
        self._origin = origin
        self._last_readings: dict[tuple[UUID, SensorKind], SensorReading] = {}
        self._fingerprints: dict[tuple[UUID, SensorKind], tuple] = {}

    @property
    def last_readings(self) -> dict[tuple[UUID, SensorKind], SensorReading]:
        return self._last_readings.copy()

    def ingest(self, devices: Any) -> list[SensorReading]:
        if not isinstance(devices, list):
            return []
        result = []
        for device in devices:
            if not isinstance(device, dict) or not isinstance(device.get("id"), str):
                continue
            binding = self._bindings.get(device["id"])
            if binding is None:
                continue
            readings = sensor_readings_from_device(
                device,
                device_id=binding.device_id,
                room_id=binding.room_id,
                now=self._clock(),
                stale_after=self._stale_after,
                origin=self._origin,
            )
            for reading in readings:
                key = (reading.device_id, reading.kind)
                self._last_readings[key] = reading
                if reading.kind is SensorKind.contact:
                    fingerprint = (reading.status, reading.contact)
                else:
                    value = (
                        reading.temperature_c
                        if reading.kind is SensorKind.temperature
                        else reading.humidity_pct
                    )
                    fingerprint = (reading.observed_at, reading.status, value)
                if self._fingerprints.get(key) != fingerprint:
                    event = SensorReadingRecorded(
                        ts=reading.ts,
                        household_id=self._household_id,
                        provenance=reading.provenance,
                        data=reading,
                    )
                    try:
                        self._publish(event)
                    except Exception as exc:
                        log.exception(
                            "publicação de sensor falhou (%s)", type(exc).__name__, exc_info=False
                        )
                    else:
                        self._fingerprints[key] = fingerprint
            result.extend(readings)
        return result

    def unavailable(self) -> None:
        self._last_readings.clear()
        self._fingerprints.clear()
