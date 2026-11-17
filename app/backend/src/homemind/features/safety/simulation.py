"""Cenários SIMULADOS (origem `simulated`) para demo e testes; nunca representam leituras reais."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import stable_id
from homemind.contracts.sensors import (
    ContactState,
    SensorKind,
    SensorReading,
    SensorStatus,
)


def contact(ts: datetime, state: ContactState | None, *, status=SensorStatus.ok,
            device=fx.WINDOW_SENSOR, room: UUID | None = fx.ROOM_SALA) -> de.SensorReadingRecorded:  # fmt: skip # noqa: E501
    r = SensorReading(
        id=stable_id("sim-reading", str(device), ts.isoformat()),
        device_id=device, room_id=room, ts=ts, kind=SensorKind.contact, status=status,
        contact=state if status is SensorStatus.ok else None,
        provenance=fx.SIM_MEASURED,
    )  # fmt: skip
    return de.SensorReadingRecorded(
        id=stable_id("sim-event", r.id.hex), ts=ts, household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED, data=r,
    )  # fmt: skip


def heater_on(ts: datetime) -> de.EnergyConsumptionDetected:
    c = fx.consumption().model_copy(update={"started_at": ts})
    return de.EnergyConsumptionDetected(
        id=stable_id("sim-event", "heater-on", ts.isoformat()), ts=ts,
        household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c,
    )  # fmt: skip


def heater_off(ts: datetime) -> de.EnergyConsumptionClosed:
    c = fx.consumption(closed=True).model_copy(update={"ended_at": ts})
    return de.EnergyConsumptionClosed(
        id=stable_id("sim-event", "heater-off", ts.isoformat()), ts=ts,
        household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c,
    )  # fmt: skip
