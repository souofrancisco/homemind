"""Tarifário de referência (ALERT-02): quanto vale um consumo antes de haver fatura.

- Simples: um preço por kWh.
- Bi-horário (simplificado, v5.1 §6.6): vazio das 22h às 08h, hora local da casa, e todo o
  sábado e domingo. Cada kWh vale o preço da hora em que foi consumido; um consumo que
  atravessa a fronteira reparte-se pelo tempo (potência constante dentro do consumo).

Origem do preço, por ordem: a tarifa definida pelo senhorio (`billing_tariff`); o preço de
referência da casa; o preço médio da última fatura fechada. Sem nenhum: `None` (custo
desconhecido, nunca 0 €). Só estima: o fecho reparte o total real da fatura.
"""

import sqlite3
from datetime import datetime, timedelta
from fractions import Fraction
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.billing import Tariff, TariffKind, TariffSource, TariffStatus
from homemind.features.billing import bills

OFFPEAK_FROM_HOUR = 22
OFFPEAK_TO_HOUR = 8


def load(conn: sqlite3.Connection, household_id: UUID) -> TariffStatus:
    row = conn.execute(
        "SELECT * FROM billing_tariff WHERE household_id = ?", (str(household_id),)
    ).fetchone()
    if row is not None:
        tariff = Tariff(
            kind=row["kind"],
            price_millicents_per_kwh=row["price_millicents_per_kwh"],
            offpeak_price_millicents_per_kwh=row["offpeak_price_millicents_per_kwh"],
        )
        return TariffStatus(tariff=tariff, source=TariffSource.configured)
    house = conn.execute(
        "SELECT energy_price_millicents_per_kwh AS p FROM household WHERE id = ?",
        (str(household_id),),
    ).fetchone()
    if house and house["p"]:
        return _simple(house["p"], TariffSource.reference)
    last = conn.execute(
        "SELECT * FROM billing_bill WHERE household_id = ? AND status = 'finalized'"
        " ORDER BY period_start DESC LIMIT 1",
        (str(household_id),),
    ).fetchone()
    if last is not None:
        return _simple(bills.to_view(last).price_millicents_per_kwh, TariffSource.last_bill)
    return TariffStatus(tariff=None, source=None)


def _simple(price: int, source: TariffSource) -> TariffStatus:
    tariff = Tariff(kind=TariffKind.simple, price_millicents_per_kwh=price)
    return TariffStatus(tariff=tariff, source=source)


def save(conn: sqlite3.Connection, household_id: UUID, tariff: Tariff, now: datetime) -> None:
    conn.execute(
        "INSERT INTO billing_tariff (household_id, kind, price_millicents_per_kwh,"
        " offpeak_price_millicents_per_kwh, updated_at) VALUES (?,?,?,?,?)"
        " ON CONFLICT(household_id) DO UPDATE SET kind = excluded.kind,"
        " price_millicents_per_kwh = excluded.price_millicents_per_kwh,"
        " offpeak_price_millicents_per_kwh = excluded.offpeak_price_millicents_per_kwh,"
        " updated_at = excluded.updated_at",
        (
            str(household_id),
            tariff.kind.value,
            tariff.price_millicents_per_kwh,
            tariff.offpeak_price_millicents_per_kwh,
            now.isoformat(),
        ),
    )


def is_offpeak(local: datetime) -> bool:
    return local.weekday() >= 5 or not OFFPEAK_TO_HOUR <= local.hour < OFFPEAK_FROM_HOUR


def value_millicents(
    tariff: Tariff, tz: ZoneInfo, energy_wh: int, started_at: datetime, ended_at: datetime | None
) -> Fraction:
    """Valor exato (milicêntimos) de `energy_wh` consumidos entre `started_at` e `ended_at`.
    Arredonda-se uma vez, no fim de cada soma (`cents`)."""
    peak = tariff.price_millicents_per_kwh
    if tariff.kind is TariffKind.simple:
        return Fraction(energy_wh * peak, 1000)
    offpeak = tariff.offpeak_price_millicents_per_kwh
    assert offpeak is not None
    end = ended_at if ended_at is not None and ended_at > started_at else None
    if end is None:  # instantâneo: o preço da hora em que começou
        price = offpeak if is_offpeak(started_at.astimezone(tz)) else peak
        return Fraction(energy_wh * price, 1000)
    total = Fraction(0)
    t = started_at
    while t < end:
        # as fronteiras do vazio são horas certas; em Portugal o fuso é de horas inteiras
        nxt = min(end, t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        price = offpeak if is_offpeak(t.astimezone(tz)) else peak
        total += Fraction((nxt - t) // timedelta(microseconds=1)) * price
        t = nxt
    span = (end - started_at) // timedelta(microseconds=1)
    return total * energy_wh / (span * 1000)


def cents(millicents: Fraction) -> int:
    """Arredonda uma vez ao cêntimo mais próximo (empate ao par, como `cost_cents`)."""
    return round(millicents / 1000)
