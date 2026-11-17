"""Entrada e validação da fatura (BILL-01): regras puras e persistência em `billing_bill`.

A fatura é o valor REAL a repartir: nunca se estima nem se completa. O que não fecha é
recusado (`bill_inconsistent`) com a razão, para o senhorio corrigir o que copiou.
"""

import sqlite3
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID

from homemind.contracts.billing import (
    BillIn,
    BillInconsistentError,
    BillPeriod,
    BillPreview,
    BillSource,
    BillStatus,
    BillView,
    ElectricityBill,
)
from homemind.contracts.common import Audit, Origin, Provenance, ValueKind, cost_cents

# Preço médio plausível da energia, com impostos: 0,01–1,00 €/kWh. Fora disto é quase
# sempre um erro de unidades (kWh vs Wh, euros vs cêntimos). PROPOSTA (ajustável).
PRICE_MIN_MILLICENTS = 1_000
PRICE_MAX_MILLICENTS = 100_000
MAX_DAYS = 62  # faturas mensais ou bimestrais


def price_millicents(energy_cents: int, total_wh: int) -> int:
    """Preço médio da energia em milicêntimos/kWh (1 cêntimo = 1000 milicêntimos)."""
    return round(Fraction(energy_cents * 1_000_000, total_wh))


def tolerance_cents(energy_cents: int) -> int:
    """Folga ao conferir com a tarifa declarada (arredondamentos por linha da fatura):
    1 % da parcela de energia, no mínimo 5 cêntimos. PROPOSTA."""
    return max(5, energy_cents // 100)


def check_bill(bill: BillIn, today: date, real_household: bool) -> BillPreview:
    """Valida o que o senhorio escreveu; devolve a pré-visualização ou levanta
    `BillInconsistentError` com uma razão legível."""
    if bill.origin is Origin.simulated and real_household:
        raise BillInconsistentError("fatura simulada numa casa real")
    if bill.period.end > today:
        raise BillInconsistentError("o período da fatura ainda não terminou")
    if bill.period.days > MAX_DAYS:
        raise BillInconsistentError(f"período acima de {MAX_DAYS} dias")
    if bill.fixed_cents >= bill.total_cents:
        raise BillInconsistentError("a parcela fixa tem de ser menor do que o total")
    energy = bill.total_cents - bill.fixed_cents
    price = price_millicents(energy, bill.total_wh)
    if not PRICE_MIN_MILLICENTS <= price <= PRICE_MAX_MILLICENTS:
        raise BillInconsistentError(
            "preço médio da energia fora de 0,01–1,00 €/kWh: confirmar kWh e valores"
        )
    declared = bill.price_millicents_per_kwh
    if declared is not None:
        if not PRICE_MIN_MILLICENTS <= declared <= PRICE_MAX_MILLICENTS:
            raise BillInconsistentError("tarifa fora de 0,01–1,00 €/kWh")
        if abs(cost_cents(bill.total_wh, declared) - energy) > tolerance_cents(energy):
            raise BillInconsistentError("os valores não fecham: total − fixa ≠ kWh × tarifa")
    return BillPreview(
        period=bill.period,
        days=bill.period.days,
        total_cents=bill.total_cents,
        fixed_cents=bill.fixed_cents,
        energy_cents=energy,
        total_wh=bill.total_wh,
        price_millicents_per_kwh=price,
        origin=bill.origin,
    )


def new_bill(
    bill_id: UUID, household_id: UUID, bill: BillIn, by_resident: UUID, now: datetime
) -> ElectricityBill:
    return ElectricityBill(
        id=bill_id,
        household_id=household_id,
        period=bill.period,
        total_cents=bill.total_cents,
        fixed_cents=bill.fixed_cents,
        total_wh=bill.total_wh,
        source=BillSource.manual,
        provenance=Provenance(origin=bill.origin, kind=ValueKind.measured),  # copiado da fatura
        created_by=Audit(at=now, by_resident_id=by_resident),
    )


# --- persistência ---------------------------------------------------------------------------


def overlaps(conn: sqlite3.Connection, household_id: UUID, period: BillPeriod) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM billing_bill WHERE household_id = ? AND status != 'superseded'"
            " AND period_start <= ? AND period_end >= ?",
            (str(household_id), period.end.isoformat(), period.start.isoformat()),
        ).fetchone()
        is not None
    )


def insert_bill(conn: sqlite3.Connection, bill: ElectricityBill, declared: int | None) -> None:
    conn.execute(
        "INSERT INTO billing_bill (id, household_id, period_start, period_end, total_cents,"
        " fixed_cents, total_wh, declared_price_millicents_per_kwh, source, status, origin, kind,"
        " revision, supersedes_id, created_at, created_by_resident_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(bill.id),
            str(bill.household_id),
            bill.period.start.isoformat(),
            bill.period.end.isoformat(),
            bill.total_cents,
            bill.fixed_cents,
            bill.total_wh,
            declared,
            bill.source.value,
            bill.status.value,
            bill.provenance.origin.value,
            bill.provenance.kind.value,
            bill.revision,
            str(bill.supersedes_id) if bill.supersedes_id else None,
            bill.created_by.at.isoformat(),
            str(bill.created_by.by_resident_id),
        ),
    )


def list_bills(
    conn: sqlite3.Connection, household_id: UUID, statuses: tuple[BillStatus, ...]
) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT * FROM billing_bill WHERE household_id = ? AND status IN ({marks})"
        " ORDER BY period_start DESC, revision DESC",
        (str(household_id), *(s.value for s in statuses)),
    ).fetchall()


def get_bill(conn: sqlite3.Connection, household_id: UUID, bill_id: UUID) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM billing_bill WHERE household_id = ? AND id = ?",
        (str(household_id), str(bill_id)),
    ).fetchone()


def to_view(row: sqlite3.Row) -> BillView:
    return BillView(
        id=row["id"],
        period=BillPeriod(start=row["period_start"], end=row["period_end"]),
        total_cents=row["total_cents"],
        fixed_cents=row["fixed_cents"],
        total_wh=row["total_wh"],
        price_millicents_per_kwh=price_millicents(
            row["total_cents"] - row["fixed_cents"], row["total_wh"]
        ),
        status=row["status"],
        source=row["source"],
        provenance=Provenance(origin=row["origin"], kind=row["kind"]),
        revision=row["revision"],
        created_at=row["created_at"],
    )
