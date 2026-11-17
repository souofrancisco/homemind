from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from homemind.connectors.mcp_energy import reading_from_device
from homemind.contracts.devices import PowerUnit
from homemind.contracts.domain_events import EnergyReadingRecorded
from homemind.contracts.energy import EnergyReading

log = logging.getLogger(__name__)


class EnergyCollector:
    def __init__(
        self,
        *,
        household_id: UUID,
        device_id: UUID,
        unit: PowerUnit | str = PowerUnit.unknown,
        publish: Callable[[EnergyReadingRecorded], object],
        stale_after: timedelta = timedelta(seconds=90),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._household_id = household_id
        self._device_id = device_id
        # `Settings.mcp_instantpower_unit` vem como "" quando não configurada.
        self._unit = PowerUnit(unit) if unit else PowerUnit.unknown
        self._publish = publish
        self._stale_after = stale_after
        self._clock = clock
        self._last_reading: EnergyReading | None = None
        self._fingerprint: tuple | None = None

    @property
    def last_reading(self) -> EnergyReading | None:
        return self._last_reading

    def ingest(self, plug: dict[str, Any] | None) -> EnergyReading | None:
        if plug is None:
            return None
        reading = reading_from_device(
            plug,
            device_id=self._device_id,
            now=self._clock(),
            unit_override=self._unit,
            stale_after=self._stale_after,
        )
        self._last_reading = reading
        fingerprint = (reading.observed_at, reading.status, reading.raw_value)
        if fingerprint != self._fingerprint:
            event = EnergyReadingRecorded(
                ts=reading.ts,
                household_id=self._household_id,
                provenance=reading.provenance,
                data=reading,
            )
            try:
                self._publish(event)
            except Exception as exc:
                log.exception(
                    "publicação de energia falhou (%s)", type(exc).__name__, exc_info=False
                )
            else:
                self._fingerprint = fingerprint
        return reading

    def unavailable(self) -> None:
        self._last_reading = None
        self._fingerprint = None
