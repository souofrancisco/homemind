"""Conversão pura de uma capability instantPower para o contrato EnergyReading."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from homemind.connectors.mcp_home import _UNIT_FACTOR, _capabilities
from homemind.contracts.common import Origin, Provenance, ValueKind, new_id
from homemind.contracts.devices import PowerUnit
from homemind.contracts.energy import EnergyReading, ReadingStatus

_UNIT_BY_NAME = {
    "W": PowerUnit.W,
    "w": PowerUnit.W,
    "dW": PowerUnit.dW,
    "mW": PowerUnit.mW,
    "milliwatt": PowerUnit.mW,
}


def reading_from_device(
    device: dict[str, Any],
    *,
    device_id: UUID,
    now: datetime,
    unit_override: PowerUnit = PowerUnit.unknown,
    stale_after: timedelta = timedelta(seconds=90),
) -> EnergyReading:
    """Converte os dados MCP, tratando payloads inválidos como leituras em falta."""
    observed_at = None
    try:
        timestamp = device.get("lastCommunicationTime")
        if (
            isinstance(timestamp, int | float)
            and not isinstance(timestamp, bool)
            and math.isfinite(timestamp)
            and timestamp > 0
        ):
            candidate = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            if candidate <= now:
                observed_at = candidate
    except (AttributeError, OverflowError, OSError, TypeError, ValueError):
        pass

    try:
        cap = _capabilities(device).get("instantPower", {})
        raw = cap.get("value")
    except (AttributeError, KeyError, TypeError, ValueError):
        cap, raw = {}, None

    try:
        raw_number = (
            float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None
        )
        valid_raw = raw_number is not None and math.isfinite(raw_number) and raw_number >= 0
    except (OverflowError, TypeError, ValueError):
        raw_number, valid_raw = None, False
    status = ReadingStatus.missing
    power_w = None
    raw_value = None
    raw_unit = PowerUnit.unknown

    if valid_raw:
        raw_value = raw_number
        declared = cap.get("unit") or cap.get("unitOfMeasure")
        unit = declared if declared else str(unit_override or "")
        known = isinstance(unit, str)
        factor = _UNIT_FACTOR.get(unit) if known else None
        raw_unit = _UNIT_BY_NAME.get(unit, PowerUnit.unknown) if known else PowerUnit.unknown
        if factor is None or raw_unit is PowerUnit.unknown:
            status = ReadingStatus.unit_unknown
        else:
            converted = raw_value * factor
            if not math.isfinite(converted) or converted > 100_000:
                raw_value = None
                status = ReadingStatus.missing
            elif observed_at is not None and now - observed_at > stale_after:
                status = ReadingStatus.stale
            else:
                power_w = converted
                status = ReadingStatus.ok

    provenance = Provenance(
        origin=Origin.real,
        kind=ValueKind.measured if status is ReadingStatus.ok else ValueKind.estimated,
    )
    return EnergyReading(
        id=new_id(),
        device_id=device_id,
        ts=now,
        observed_at=observed_at,
        status=status,
        power_w=power_w,
        raw_value=raw_value,
        raw_unit=raw_unit,
        provenance=provenance,
    )
