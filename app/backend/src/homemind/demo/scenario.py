"""Cenário de referência offline DEMO-01. Não contém motores NILM/billing/notificações.

Todos os eventos são roteirizados, com IDs e relógio fixos. A origem é SIMULATED;
a confiança é um *input ilustrativo*, nunca o resultado de um classificador real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel

from homemind.contracts import billing, devices, domain_events as ev, energy, fixtures as fx
from homemind.contracts import notification, presence
from homemind.contracts.common import Audit, Provenance, replace, stable_id


@dataclass(frozen=True)
class DemoClock:
    start: datetime = fx.T0

    def at(self, minute: int) -> datetime:
        return self.start + timedelta(minutes=minute)


CLOCK = DemoClock()
# (minuto virtual, W agregados). A tomada na bancada é o medidor da extensão
# montada na sala. Os valores são ficcionais, não uma aquisição MCP.
POWER_PROFILE = (
    (0, 40.0),
    (1, 1840.0),
    (4, 40.0),
    (10, 2040.0),
    (70, 2040.0),
    (130, 40.0),
    (140, 940.0),
    (144, 40.0),
    (147, 2040.0),
    (149, 40.0),
)


def kettle() -> devices.Appliance:
    return devices.Appliance(
        id=fx.KETTLE,
        household_id=fx.HOUSEHOLD,
        name="Chaleira comum",
        category=devices.ApplianceCategory.kitchen,
        ownership=devices.ApplianceOwnership(scope=devices.ApplianceScope.common),
        typical_watts=1800,
        registered_by_resident_id=fx.ANA,
    )


def kettle_signature() -> devices.ApplianceSignature:
    return devices.ApplianceSignature(
        id=stable_id("signature", "chaleira-sala"),
        appliance_id=fx.KETTLE,
        watts_mean=1800,
        watts_tolerance=120,
        duration_typical_s=180,
        pattern=devices.SignaturePattern.short,
        samples=8,
        origin=devices.SignatureOrigin.simulated,
        updated_at=fx.T0,
    )


def references() -> list[tuple[str, UUID, BaseModel]]:
    """Catálogo tipado, incluindo as DUAS faturas distintas de referência v5.1.

    As alocações são valores de fixtures, não resultados de um motor de faturação.
    """
    a, a_alloc = fx.bill_a()
    b, b_alloc = fx.bill_b()
    billing.validate_allocations(a, a_alloc)
    billing.validate_allocations(b, b_alloc)
    if a.id == b.id or [x.amount_cents for x in a_alloc] == [x.amount_cents for x in b_alloc]:
        raise AssertionError("as duas repartições devem permanecer distintas")
    rows: list[tuple[str, UUID, BaseModel]] = [
        ("device", fx.METER, fx.meter()),
        ("appliance", fx.HEATER, fx.heater()),
        ("appliance", fx.KETTLE, kettle()),
        ("signature", fx.heater_signature().id, fx.heater_signature()),
        ("signature", kettle_signature().id, kettle_signature()),
        ("budget", fx.budget().id, fx.budget()),
        ("reference_bill", a.id, a),
        ("reference_bill", b.id, b),
    ]
    rows.extend(("reference_allocation", x.id, x) for x in [*a_alloc, *b_alloc])
    return rows


def power_samples() -> list[energy.EnergyReading]:
    return [fx.reading(power_w=w, ts=CLOCK.at(minute)) for minute, w in POWER_PROFILE]


def _episode(
    name: str,
    start: int,
    end: int,
    watts: int,
    match: energy.ApplianceMatch,
    *,
    location: energy.LocationKind,
    room_id: UUID | None,
    closed: bool,
) -> energy.ConsumptionEvent:
    wh = watts * (end - start) // 60 if closed else 0
    return energy.ConsumptionEvent(
        id=fx.CONSUMPTION if name == "heater" else stable_id("demo-consumption", name),
        household_id=fx.HOUSEHOLD,
        device_id=fx.METER,
        match=match,
        started_at=CLOCK.at(start),
        ended_at=CLOCK.at(end) if closed else None,
        status=energy.ConsumptionStatus.closed if closed else energy.ConsumptionStatus.ongoing,
        peak_w=float(watts + 40),
        energy_wh=wh,
        location=location,
        room_id=room_id,
        cost_estimate=energy.CostEstimate(
            cents=fx.cost_cents(wh, fx.PRICE_MILLICENTS),
            price_millicents_per_kwh=fx.PRICE_MILLICENTS,
        ),
        provenance=fx.SIM_INFERRED,
    )


def events() -> list[ev.EventBase]:
    """Eventos tipados: sem rede, heurísticas, deteção de imagem ou cálculo financeiro."""
    out: list[ev.EventBase] = []
    correlation = stable_id("demo", "official-correlation")

    def add(
        name: str, cls: type[ev.EventBase], minute: int, data: BaseModel, provenance: Provenance
    ) -> None:
        out.append(
            cls(
                id=stable_id("demo-event", name),
                household_id=fx.HOUSEHOLD,
                correlation_id=correlation,
                ts=CLOCK.at(minute),
                provenance=provenance,
                data=data,
            )
        )

    prev: float | None = None
    for minute, w in POWER_PROFILE:
        reading = fx.reading(power_w=w, ts=CLOCK.at(minute))
        add(f"reading-{minute}", ev.EnergyReadingRecorded, minute, reading, fx.SIM_MEASURED)
        if prev is not None and w != prev:
            step = energy.PowerStep(
                id=stable_id("demo-step", str(minute)),
                device_id=fx.METER,
                ts=CLOCK.at(minute),
                before_w=prev,
                after_w=w,
                provenance=fx.SIM_MEASURED,
            )
            add(f"step-{minute}", ev.EnergyStepDetected, minute, step, fx.SIM_MEASURED)
        prev = w

    kettle_match = energy.ApplianceMatch(
        appliance_id=fx.KETTLE,
        confidence=0.88,
        candidates=[energy.ApplianceCandidate(appliance_id=fx.KETTLE, confidence=0.88)],
    )
    heater_match = fx.consumption().match
    ambiguous_match = energy.ApplianceMatch(
        candidates=[
            energy.ApplianceCandidate(appliance_id=fx.HEATER, confidence=0.55),
            energy.ApplianceCandidate(appliance_id=fx.KETTLE, confidence=0.45),
        ]
    )
    cases = (
        ("kettle", 1, 4, 1800, kettle_match, energy.LocationKind.common, fx.ROOM_SALA),
        ("heater", 10, 130, 2000, heater_match, energy.LocationKind.common, fx.ROOM_SALA),
        ("unknown", 140, 144, 900, energy.ApplianceMatch(), energy.LocationKind.unknown, None),
        ("ambiguous", 147, 149, 2000, ambiguous_match, energy.LocationKind.unknown, None),
    )
    for name, start, end, watts, match, location, room in cases:
        args = (name, start, end, watts, match)
        kwargs = dict(location=location, room_id=room)
        add(
            name + "-on",
            ev.EnergyConsumptionDetected,
            start,
            _episode(*args, closed=False, **kwargs),
            fx.SIM_INFERRED,
        )
        add(
            name + "-off",
            ev.EnergyConsumptionClosed,
            end,
            _episode(*args, closed=True, **kwargs),
            fx.SIM_INFERRED,
        )

    for name, minute, direction in (
        ("door-in", 9, presence.DoorDirection.entered),
        ("door-out", 125, presence.DoorDirection.left),
    ):
        # Sem resident_id, rosto, frame ou associação a pessoa.
        add(
            name,
            ev.PresenceDoorCrossed,
            minute,
            presence.DoorCrossed(
                ts=CLOCK.at(minute),
                direction=direction,
                confidence=0.93,
                provenance=fx.SIM_INFERRED,
            ),
            fx.SIM_INFERRED,
        )

    # Pedido/aceitação roteirizados; a decisão é humana, não derivada da câmara.
    req = replace(
        fx.confirmation_request(),
        estimated_cost_cents=64,
        expires_at=CLOCK.at(131) + timedelta(hours=24),
    )
    add("ask", ev.BillingConfirmationNeeded, 131, req, fx.SIM_INFERRED)
    original = fx.confirmation_notification()
    add(
        "notification",
        ev.NotificationCreated,
        132,
        ev.NotificationCreatedData(
            notification_id=original.id,
            scope=original.scope,
            kind=original.kind,
        ),
        fx.SIM_MEASURED,
    )
    answer = notification.NotificationResponse(
        notification_id=original.id,
        action_id="mine",
        resident_id=fx.CARLA,
        responded_at=CLOCK.at(133),
    )
    add(
        "answer",
        ev.NotificationResponded,
        133,
        ev.NotificationRespondedData(
            response=answer,
            ref=notification.NotificationRef(
                type=notification.RefType.consumption_event,
                id=fx.CONSUMPTION,
            ),
        ),
        fx.SIM_MEASURED,
    )
    attribution = replace(
        fx.carla_attribution(),
        decided_by=Audit(
            at=CLOCK.at(133),
            by_resident_id=fx.CARLA,
        ),
    )
    add("attribution", ev.BillingAttributionChanged, 133, attribution, fx.SIM_MEASURED)
    add(
        "budget-80",
        ev.AlertsThresholdCrossed,
        138,
        billing.BudgetThreshold(
            budget_id=fx.budget().id,
            pct=80,
            spent_cents=2000,
            forecast_cents=3100,
        ),
        fx.SIM_ESTIMATED,
    )
    # Falha de sensor é reproduzível: missing != 0W, não gera inferência.
    add(
        "missing-power",
        ev.EnergyReadingRecorded,
        160,
        energy.EnergyReading(
            id=stable_id("demo-reading", "missing"),
            device_id=fx.METER,
            ts=CLOCK.at(160),
            status=energy.ReadingStatus.missing,
            power_w=None,
            provenance=fx.SIM_ESTIMATED,
        ),
        fx.SIM_ESTIMATED,
    )

    out.sort(key=lambda item: item.ts)  # estável para timestamps iguais
    ids = [item.id for item in out]
    assert len(ids) == len(set(ids))
    assert all(item.provenance.simulated and item.household_id == fx.HOUSEHOLD for item in out)
    assert [
        item.data.match.outcome.value for item in out if item.type == "energy.consumption_closed"
    ] == [
        "identified",
        "identified",
        "unknown",
        "ambiguous",
    ]
    return out
