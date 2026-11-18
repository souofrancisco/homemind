"""Cenário de referência offline DEMO-01. Não contém motores NILM/billing/notificações.

Todos os eventos são roteirizados, com IDs e relógio fixos. A origem é SIMULATED;
a confiança é um *input ilustrativo*, nunca o resultado de um classificador real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel

from homemind.contracts import billing, devices, energy, presence
from homemind.contracts import domain_events as ev
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Provenance, stable_id


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
    (159, 0.0),
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


def events() -> list[ev.EventBase]:
    """Entradas tipadas: sem rede, classificadores, identidade ou cálculo financeiro."""
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

    for minute, w in POWER_PROFILE:
        reading = fx.reading(power_w=w, ts=CLOCK.at(minute))
        add(f"reading-{minute}", ev.EnergyReadingRecorded, minute, reading, fx.SIM_MEASURED)

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

    add(
        "budget-80",
        ev.AlertsThresholdCrossed,
        138,
        billing.BudgetThreshold(
            budget_id=fx.budget().id,
            resident_id=fx.budget().resident_id,
            period=fx.budget().period,
            pct=80,
            spent_cents=2000,
            limit_cents=fx.budget().limit_cents,
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
    return out
