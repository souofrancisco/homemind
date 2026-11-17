"""Adaptadores puros de sensores MCP para o contrato SensorReading."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from homemind.connectors.mcp_energy import observed_at_from_device
from homemind.connectors.mcp_home import _capabilities
from homemind.contracts.common import Origin, Provenance, ValueKind, new_id
from homemind.contracts.sensors import (
    ContactState,
    SensorKind,
    SensorReading,
    SensorStatus,
)

DEFAULT_STALE_AFTER: dict[SensorKind, timedelta] = {
    SensorKind.contact: timedelta(minutes=3),
    SensorKind.temperature: timedelta(minutes=30),
    SensorKind.humidity: timedelta(minutes=30),
}


def sensor_readings_from_device(
    device: dict[str, Any],
    *,
    device_id: UUID,
    now: datetime,
    room_id: UUID | None = None,
    stale_after: Mapping[SensorKind, timedelta] | None = None,
) -> list[SensorReading]:
    """Converte contacto ou clima; tipos e valores não suportados ficam desconhecidos."""
    device_type = device.get("type")
    if not isinstance(device_type, str):  # um `type` não-hashable não pode rebentar o `.get`
        return []
    kinds = {
        "contactSensor": (SensorKind.contact,),
        "temperatureSensor": (SensorKind.temperature, SensorKind.humidity),
    }.get(device_type, ())
    if not kinds:
        return []

    limits = stale_after or {}
    observed_at = observed_at_from_device(device, now)
    try:
        capabilities = _capabilities(device)
    except (AttributeError, KeyError, TypeError, ValueError):
        capabilities = {}

    result = []
    for kind in kinds:
        cap_name = {
            SensorKind.contact: "sensorState",
            SensorKind.temperature: "temperatureValue",
            SensorKind.humidity: "humidityValue",
        }[kind]
        try:
            raw = capabilities.get(cap_name, {}).get("value")
        except (AttributeError, TypeError, ValueError):
            raw = None

        value: ContactState | float | None
        if kind is SensorKind.contact:
            value = (
                {"alarm": ContactState.open, "normal": ContactState.closed}.get(raw)
                if isinstance(raw, str)
                else None
            )
        else:
            value = None
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                try:
                    number = float(raw)
                    low, high = (-40, 85) if kind is SensorKind.temperature else (0, 100)
                    if math.isfinite(number) and low <= number <= high:
                        value = number
                except (OverflowError, TypeError, ValueError):
                    pass

        status = SensorStatus.ok if value is not None else SensorStatus.unknown
        stale_limit = limits.get(kind, DEFAULT_STALE_AFTER[kind])
        if value is not None and observed_at is not None and now - observed_at > stale_limit:
            value = None
            status = SensorStatus.stale

        values = {
            "contact": value if kind is SensorKind.contact else None,
            "temperature_c": value if kind is SensorKind.temperature else None,
            "humidity_pct": value if kind is SensorKind.humidity else None,
        }
        result.append(
            SensorReading(
                id=new_id(),
                device_id=device_id,
                room_id=room_id,
                ts=now,
                observed_at=observed_at,
                kind=kind,
                status=status,
                **values,
                provenance=Provenance(
                    origin=Origin.real,
                    kind=ValueKind.measured if status is SensorStatus.ok else ValueKind.estimated,
                ),
            )
        )
    return result
