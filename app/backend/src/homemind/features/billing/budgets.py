"""Orçamento mensal pessoal e avisos 50/80/100 % (ALERT-01).

Gasto do mês = TODOS os custos (D-31), o que o morador pagaria se o mês fechasse agora:
- `confirmed`: consumo atribuído a si (quarto, confirmação) × preço;
- `shared`: a sua parte igual dos consumos da conta comum × preço;
- `base`: parte do termo fixo + resíduo, estimada pelo último recibo fechado (por dia) e
  proporcional aos dias já passados; `None` se ainda não há recibo anterior.
Preço: o de referência da casa; senão o preço médio da última fatura; sem nenhum → gasto
desconhecido (`None`, nunca 0 €). Com a fatura do mês fechada, valem os valores reais.

Avisos: um por limiar e ciclo; ao saltar vários limiares de uma vez avisa-se só o mais alto
(os de baixo contam como avisados). Redefinir o orçamento é um reset explícito (`generation`).
"""

import calendar
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.billing import (
    AttributionTarget,
    BillAllocation,
    BillPeriod,
    BreakdownKind,
    Budget,
    BudgetKind,
    BudgetStatus,
    BudgetThreshold,
)
from homemind.contracts.common import Origin, Provenance, ValueKind, cost_cents, stable_id
from homemind.features.billing import bills
from homemind.features.billing.closing import period_inputs, tenants_in_period


def month_period(period: str) -> BillPeriod:
    y, m = (int(x) for x in period.split("-"))
    return BillPeriod(start=date(y, m, 1), end=date(y, m, calendar.monthrange(y, m)[1]))


def local_today(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> date:
    tz = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()["timezone"]
    return now.astimezone(ZoneInfo(tz)).date()


def current_period(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> str:
    return local_today(conn, household_id, now).strftime("%Y-%m")


@dataclass(frozen=True)
class Spend:
    confirmed_cents: int
    shared_cents: int
    base_cents: int | None
    final: bool
    simulated: bool

    @property
    def total_cents(self) -> int:
        return self.confirmed_cents + self.shared_cents + (self.base_cents or 0)

    @property
    def provenance(self) -> Provenance:
        kind = ValueKind.measured if self.final else ValueKind.estimated
        origin = Origin.simulated if self.simulated else Origin.real
        return Provenance(origin=origin, kind=kind)


def month_spend(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, period: str, now: datetime
) -> Spend | None:
    month = month_period(period)
    final = _final_allocation(conn, household_id, resident_id, month)
    if final is not None:
        allocation, simulated = final
        lines = {k: 0 for k in BreakdownKind}
        for line in allocation.breakdown:
            lines[line.kind] += line.amount_cents
        return Spend(
            confirmed_cents=lines[BreakdownKind.room] + lines[BreakdownKind.appliance],
            shared_cents=lines[BreakdownKind.common],
            base_cents=allocation.fixed_share_cents + allocation.residual_share_cents,
            final=True,
            simulated=simulated,
        )
    tenants = tenants_in_period(conn, household_id, month)
    if resident_id not in tenants:
        return None
    last = _last_finalized(conn, household_id, month.start)
    price = _reference_price(conn, household_id) or (last and last["price"])
    if not price:
        return None  # sem preço não há custo: desconhecido, nunca 0 €
    attributions, consumptions = period_inputs(conn, household_id, month)
    own_wh, shared_wh, simulated = 0, Fraction(0), False
    for a in attributions:
        c = consumptions[a.consumption_event_id]
        if not c.energy_wh:
            continue
        simulated = simulated or c.provenance.simulated
        if a.target_type is AttributionTarget.resident and a.target_resident_id == resident_id:
            own_wh += c.energy_wh
        elif a.target_type is AttributionTarget.common:
            shared_wh += Fraction(c.energy_wh, len(tenants))
    base = None
    if last is not None and resident_id in last["base_per_day"]:
        today = local_today(conn, household_id, now)
        elapsed = max(0, (min(today, month.end) - month.start).days + 1)
        base = round(last["base_per_day"][resident_id] * elapsed)
        simulated = simulated or last["simulated"]
    return Spend(
        confirmed_cents=cost_cents(own_wh, price),
        shared_cents=round(shared_wh * price / 1_000_000),
        base_cents=base,
        final=False,
        simulated=simulated,
    )


def _reference_price(conn: sqlite3.Connection, household_id: UUID) -> int | None:
    row = conn.execute(
        "SELECT energy_price_millicents_per_kwh AS p FROM household WHERE id = ?",
        (str(household_id),),
    ).fetchone()
    return row["p"] if row else None


def _final_allocation(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, month: BillPeriod
) -> tuple[BillAllocation, bool] | None:
    row = conn.execute(
        "SELECT a.json, b.origin FROM billing_allocation a JOIN billing_bill b ON b.id = a.bill_id"
        " WHERE b.household_id = ? AND b.status = 'finalized' AND b.period_start = ?"
        " AND a.resident_id = ?",
        (str(household_id), month.start.isoformat(), str(resident_id)),
    ).fetchone()
    if row is None:
        return None
    return BillAllocation.model_validate_json(row["json"]), row["origin"] == "simulated"


def _last_finalized(conn: sqlite3.Connection, household_id: UUID, before: date) -> dict | None:
    row = conn.execute(
        "SELECT * FROM billing_bill WHERE household_id = ? AND status = 'finalized'"
        " AND period_start < ? ORDER BY period_start DESC LIMIT 1",
        (str(household_id), before.isoformat()),
    ).fetchone()
    if row is None:
        return None
    view = bills.to_view(row)
    allocations = conn.execute(
        "SELECT json FROM billing_allocation WHERE bill_id = ?", (row["id"],)
    ).fetchall()
    per_day = {}
    for r in allocations:
        a = BillAllocation.model_validate_json(r["json"])
        per_day[a.resident_id] = Fraction(
            a.fixed_share_cents + a.residual_share_cents, view.period.days
        )
    return {
        "price": view.price_millicents_per_kwh,
        "base_per_day": per_day,
        "simulated": view.provenance.simulated,
    }


# --- orçamentos -------------------------------------------------------------------------------


def _budget(row: sqlite3.Row) -> Budget:
    return Budget(
        id=row["id"],
        household_id=row["household_id"],
        kind=row["kind"],
        resident_id=row["resident_id"],
        room_id=row["room_id"],
        period=row["period"],
        limit_cents=row["limit_cents"],
        limit_wh=row["limit_wh"],
        thresholds=json.loads(row["thresholds"]),
        last_threshold_notified=row["last_threshold_notified"],
    )


def get_personal(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, period: str
) -> tuple[Budget, int] | None:
    row = conn.execute(
        "SELECT * FROM billing_budget WHERE household_id = ? AND kind = 'personal'"
        " AND resident_id = ? AND period = ?",
        (str(household_id), str(resident_id), period),
    ).fetchone()
    return (_budget(row), row["generation"]) if row else None


def set_personal(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    period: str,
    limit_cents: int,
    thresholds: list[int],
    now: datetime,
) -> None:
    """Cria ou redefine (reset explícito: limiares por avisar, nova `generation`)."""
    budget_id = stable_id("budget", str(household_id), str(resident_id), period)
    conn.execute(
        "INSERT INTO billing_budget (id, household_id, kind, resident_id, period, limit_cents,"
        " thresholds, last_threshold_notified, generation, updated_at)"
        " VALUES (?,?,'personal',?,?,?,?,NULL,1,?)"
        " ON CONFLICT(id) DO UPDATE SET limit_cents = excluded.limit_cents,"
        " thresholds = excluded.thresholds, last_threshold_notified = NULL,"
        " generation = generation + 1, updated_at = excluded.updated_at",
        (
            str(budget_id),
            str(household_id),
            str(resident_id),
            period,
            limit_cents,
            json.dumps(thresholds),
            now.isoformat(),
        ),
    )


def pct_of(spent_cents: int, limit_cents: int) -> int:
    return spent_cents * 100 // limit_cents


def threshold_to_notify(budget: Budget, pct: int) -> int | None:
    """O limiar mais alto atingido e ainda não avisado neste ciclo."""
    done = budget.last_threshold_notified or 0
    reached = [t for t in budget.thresholds if pct >= t and t > done]
    return max(reached) if reached else None


def status(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, period: str, now: datetime
) -> BudgetStatus:
    found = get_personal(conn, household_id, resident_id, period)
    budget = found[0] if found else None
    spend = month_spend(conn, household_id, resident_id, period, now)
    total = spend.total_cents if spend else None
    return BudgetStatus(
        period=period,
        budget=budget,
        spent_cents=total,
        confirmed_cents=spend.confirmed_cents if spend else None,
        shared_cents=spend.shared_cents if spend else None,
        base_cents=spend.base_cents if spend else None,
        pct=pct_of(total, budget.limit_cents) if budget and total is not None else None,
        final=spend.final if spend else False,
        provenance=spend.provenance if spend else None,
        as_of=now,
    )


def evaluate(
    conn: sqlite3.Connection, household_id: UUID, period: str, now: datetime
) -> list[de.DomainEvent]:
    """Reavalia os orçamentos pessoais da casa no período; grava o limiar avisado e devolve
    os `alerts.threshold_crossed` a publicar (ids derivados: idempotentes)."""
    rows = conn.execute(
        "SELECT * FROM billing_budget WHERE household_id = ? AND kind = 'personal'"
        " AND period = ? ORDER BY resident_id",
        (str(household_id), period),
    ).fetchall()
    events: list[de.DomainEvent] = []
    for row in rows:
        budget = _budget(row)
        assert budget.kind is BudgetKind.personal and budget.resident_id and budget.limit_cents
        spend = month_spend(conn, household_id, budget.resident_id, period, now)
        if spend is None:
            continue  # gasto desconhecido: não se avisa com números inventados
        pct = pct_of(spend.total_cents, budget.limit_cents)
        threshold = threshold_to_notify(budget, pct)
        if threshold is None:
            continue
        conn.execute(
            "UPDATE billing_budget SET last_threshold_notified = ? WHERE id = ?",
            (threshold, str(budget.id)),
        )
        events.append(
            de.AlertsThresholdCrossed(
                id=stable_id(
                    "alerts.threshold_crossed",
                    str(budget.id),
                    str(row["generation"]),
                    str(threshold),
                ),
                ts=now,
                household_id=household_id,
                correlation_id=stable_id("correlation", "budget", str(budget.id)),
                provenance=spend.provenance,
                data=BudgetThreshold(
                    budget_id=budget.id,
                    resident_id=budget.resident_id,
                    period=period,
                    pct=threshold,
                    spent_cents=spend.total_cents,
                    limit_cents=budget.limit_cents,
                ),
            )
        )
    return events


def evaluate_all(conn: sqlite3.Connection, now: datetime) -> list[de.DomainEvent]:
    """Todas as casas com orçamentos no mês corrente (tarefa periódica: a base estimada cresce
    com os dias, mesmo sem eventos novos)."""
    houses = [
        UUID(r["household_id"])
        for r in conn.execute("SELECT DISTINCT household_id FROM billing_budget")
    ]
    events: list[de.DomainEvent] = []
    for h in houses:
        events += evaluate(conn, h, current_period(conn, h, now), now)
    return events


# --- consumidor do barramento ------------------------------------------------------------------

# Nome PERMANENTE (chave de idempotência em `processed_event`).
CONSUMER = "billing.budgets"
EVENT_TYPES = ("billing.attribution_changed", "billing.allocation_published")


def handle(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
    """Uma atribuição nova ou uma fatura fechada podem mudar o gasto: reavaliar esse mês."""
    ev = stored.event
    if isinstance(ev, de.BillingAttributionChanged):
        row = conn.execute(
            "SELECT started_at FROM billing_consumption WHERE id = ?",
            (str(ev.data.consumption_event_id),),
        ).fetchone()
        if row is None:
            return []
        at = datetime.fromisoformat(row["started_at"])
        return evaluate(conn, ev.household_id, current_period(conn, ev.household_id, at), ev.ts)
    if isinstance(ev, de.BillingAllocationPublished):
        row = conn.execute(
            "SELECT period_start FROM billing_bill WHERE id = ?", (str(ev.data.bill_id),)
        ).fetchone()
        if row is None:
            return []
        return evaluate(conn, ev.household_id, row["period_start"][:7], ev.ts)
    return []
