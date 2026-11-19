"""Eventos e regras SIMULADOS (origem `simulated`) para a demo e os testes do motor; nunca são
leituras reais. Modelo: `features/safety/simulation.py`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.agent import (
    AutomationRule,
    AutomationSource,
    AutomationStatus,
    AutomationTrigger,
    DeviceCapability,
    DeviceCommand,
    TriggerKind,
)
from homemind.contracts.common import Provenance, stable_id
from homemind.contracts.devices import PowerUnit
from homemind.contracts.energy import EnergyReading, ReadingStatus
from homemind.contracts.presence import (
    PersonPresence,
    PresenceSource,
    PresenceState,
    UncertainReason,
)


def power_rule(
    key: str = "r1", *, device: UUID = fx.METER, target: UUID | None = None,
    threshold_w: float = 1500, duration_s: int = 600, house: UUID = fx.HOUSEHOLD,
    status: AutomationStatus = AutomationStatus.active,
) -> AutomationRule:  # fmt: skip
    return _rule(
        key, AutomationTrigger(
            kind=TriggerKind.power_above, device_id=device, threshold_w=threshold_w,
            duration_s=duration_s,
        ), target or device, house, status,
    )  # fmt: skip


def presence_rule(
    key: str = "p1", *, target: UUID = fx.METER, house: UUID = fx.HOUSEHOLD,
    status: AutomationStatus = AutomationStatus.active,
) -> AutomationRule:  # fmt: skip
    return _rule(key, AutomationTrigger(kind=TriggerKind.presence_changed), target, house, status)


def _rule(key, trigger, target, house, status) -> AutomationRule:
    return AutomationRule(
        id=stable_id("sim-rule", key), household_id=house, name=f"Regra {key}",
        source=AutomationSource.manual, trigger=trigger,
        actions=[
            DeviceCommand(target_device_id=target, capability=DeviceCapability.power, power=False)
        ],
        status=status, created_by_resident_id=fx.ANA,
        approved_by_resident_id=fx.BRUNO if status is AutomationStatus.active else None,
    )  # fmt: skip


def reading(
    ts: datetime, power_w: float | None, *, device: UUID = fx.METER, house: UUID = fx.HOUSEHOLD,
    prov: Provenance = fx.SIM_MEASURED, status: ReadingStatus = ReadingStatus.ok,
) -> de.EnergyReadingRecorded:  # fmt: skip
    r = EnergyReading(
        id=stable_id("sim-reading", str(device), ts.isoformat()), device_id=device, ts=ts,
        observed_at=ts, status=status,
        power_w=power_w if status is ReadingStatus.ok else None,
        raw_value=power_w if status is ReadingStatus.ok else None,
        raw_unit=PowerUnit.W if status is ReadingStatus.ok else PowerUnit.unknown,
        provenance=prov,
    )  # fmt: skip
    return de.EnergyReadingRecorded(
        id=stable_id("sim-event", "reading", str(device), ts.isoformat()), ts=ts,
        household_id=house, provenance=prov, data=r,
    )  # fmt: skip


def closed(ts: datetime, *, device: UUID = fx.METER) -> de.EnergyConsumptionClosed:
    c = fx.consumption(closed=True).model_copy(update={"device_id": device, "ended_at": ts})
    return de.EnergyConsumptionClosed(
        id=stable_id("sim-event", "closed", ts.isoformat()), ts=ts, household_id=fx.HOUSEHOLD,
        provenance=c.provenance, data=c,
    )  # fmt: skip


def presence(
    ts: datetime, resident: UUID, state: PresenceState, *, house: UUID = fx.HOUSEHOLD
) -> de.PresenceChanged:
    p = PersonPresence(
        resident_id=resident, state=state, since=ts, confidence=0.8,
        provenance=fx.SIM_INFERRED, sources=[PresenceSource.wifi],
        reason=UncertainReason.conflicting_cues if state is PresenceState.uncertain else None,
    )  # fmt: skip
    return de.PresenceChanged(
        id=stable_id("sim-event", "presence", str(resident), ts.isoformat(), state.value),
        ts=ts, household_id=house, provenance=fx.SIM_INFERRED, data=p,
    )  # fmt: skip
