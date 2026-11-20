"""Orçamento mensal pessoal e avisos 50/80/100 % (ALERT-01).

Gasto do mês = TODOS os custos (D-31), o que o morador pagaria se o mês fechasse agora:
- `confirmed`: consumo atribuído a si (quarto, confirmação) × preço;
- `shared`: a sua parte igual dos consumos da conta comum e do plafond solidário (BILL-03:
  o aquecimento básico de cada quarto é de todos, como no fecho) × preço;
- `base`: parte do termo fixo + resíduo, estimada pelo último recibo fechado (por dia) e
  proporcional aos dias já passados; `None` se ainda não há recibo anterior.
Preço: o tarifário de referência (`tariff.py`: simples ou bi-horário, valorizado à hora de
cada consumo); sem nenhum → gasto desconhecido (`None`, nunca 0 €). Com a fatura do mês
fechada, valem os valores reais.

Previsão do fim do mês (ALERT-02, v5.1 M3 «extrapolação linear»): gasto variável até agora +
o mesmo ritmo nos dias que faltam + a base do mês inteiro. A observação começa no primeiro
consumo atribuído da casa no mês (antes disso não havia dados, não «zero»); com menos de
`MIN_OBSERVED_DAYS` não há previsão. A incerteza é a variação do meu custo entre dias
completos (desvio-padrão diário × √dias que faltam). Aproximação conhecida: o plafond
solidário esgota-se a meio do mês e a extrapolação linear não o antecipa.

Avisos: um por limiar e ciclo; ao saltar vários limiares de uma vez avisa-se só o mais alto
(os de baixo contam como avisados). Redefinir o orçamento é um reset explícito (`generation`).
"""

import calendar
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
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
    BudgetForecast,
    BudgetKind,
    BudgetStatus,
    BudgetThreshold,
    budget_light,
)
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.features.billing import allowance, bills, tariff
from homemind.features.billing.allocation import EnergyShare, shares_for
from homemind.features.billing.closing import (
    heating_appliances,
    period_inputs,
    room_limits,
    tenants_in_period,
)


def month_period(period: str) -> BillPeriod:
    y, m = (int(x) for x in period.split("-"))
    return BillPeriod(start=date(y, m, 1), end=date(y, m, calendar.monthrange(y, m)[1]))


MIN_OBSERVED_DAYS = 3


def household_tz(conn: sqlite3.Connection, household_id: UUID) -> ZoneInfo:
    return ZoneInfo(
        conn.execute(
            "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()["timezone"]
    )


def local_today(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> date:
    return now.astimezone(household_tz(conn, household_id)).date()


def current_period(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> str:
    return local_today(conn, household_id, now).strftime("%Y-%m")


@dataclass(frozen=True)
class Spend:
    confirmed_cents: int
    shared_cents: int
    base_cents: int | None
    final: bool
    simulated: bool
    forecast: BudgetForecast | None = None

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
            shared_cents=lines[BreakdownKind.common] + lines[BreakdownKind.heating_allowance],
            base_cents=allocation.fixed_share_cents + allocation.residual_share_cents,
            final=True,
            simulated=simulated,
        )
    tenants = tenants_in_period(conn, household_id, month)
    if resident_id not in tenants:
        return None
    last = _last_finalized(conn, household_id, month.start)
    rate = tariff.load(conn, household_id).tariff
    if rate is None:
        return None  # sem preço não há custo: desconhecido, nunca 0 €
    tz = household_tz(conn, household_id)
    attributions, consumptions = period_inputs(conn, household_id, month)
    shares, simulated = [], False
    for a in attributions:
        c = consumptions[a.consumption_event_id]
        if not c.energy_wh:
            continue
        simulated = simulated or c.provenance.simulated
        shares.extend(shares_for(a, c))

    def mine(s: EnergyShare) -> tuple[Fraction, Fraction]:
        """(próprio, parte da conta comum) em milicêntimos; a conta comum divide-se por todos."""
        c = consumptions[s.consumption_id]
        value = tariff.value_millicents(rate, tz, s.energy_wh, c.started_at, c.ended_at)
        if s.resident_id == resident_id:
            return value, Fraction(0)
        return Fraction(0), (value / len(tenants) if s.resident_id is None else Fraction(0))

    daily: defaultdict[date, Fraction] = defaultdict(Fraction)  # antes do plafond: o ritmo
    for s in shares:
        daily[consumptions[s.consumption_id].started_at.astimezone(tz).date()] += sum(mine(s))
    # Plafond solidário (BILL-03) como no fecho: o aquecimento básico do quarto é de todos.
    shares, _ = allowance.apply(
        shares,
        consumptions,
        tenants,
        room_limits(conn, household_id, month),
        heating_appliances(conn, household_id),
    )
    own = sum((mine(s)[0] for s in shares), Fraction(0))
    shared = sum((mine(s)[1] for s in shares), Fraction(0))
    base, per_day = None, None
    if last is not None and resident_id in last["base_per_day"]:
        today = local_today(conn, household_id, now)
        elapsed = max(0, (min(today, month.end) - month.start).days + 1)
        per_day = last["base_per_day"][resident_id]
        base = round(per_day * elapsed)
        simulated = simulated or last["simulated"]
    spend = Spend(
        confirmed_cents=tariff.cents(own),
        shared_cents=tariff.cents(shared),
        base_cents=base,
        final=False,
        simulated=simulated,
    )
    first = min((c.started_at for c in consumptions.values()), default=None)
    if first is None:
        return spend  # mês sem dados: nunca uma previsão
    forecast = _forecast(month, tz, now, first, own + shared, daily, per_day, spend.total_cents)
    return replace(spend, forecast=forecast)


def _forecast(
    month: BillPeriod,
    tz: ZoneInfo,
    now: datetime,
    first: datetime,
    variable: Fraction,
    daily: dict[date, Fraction],
    base_per_day: Fraction | None,
    spent_cents: int,
) -> BudgetForecast | None:
    """Extrapolação linear do gasto variável (milicêntimos) + a base do mês inteiro."""
    start = datetime.combine(month.start, time(), tz)
    end = datetime.combine(month.end + timedelta(days=1), time(), tz)
    now = min(now, end)
    since = max(first, start)
    observed = Fraction((now - since) // timedelta(seconds=1), 86_400)
    if observed < MIN_OBSERVED_DAYS:
        return None  # poucos dados: não se apresenta como previsão
    left = Fraction((end - now) // timedelta(seconds=1), 86_400)
    pace = variable / observed  # milicêntimos por dia
    expected = variable + pace * left
    # dias completos observados (o primeiro e o de hoje são parciais)
    today = now.astimezone(tz).date()
    days = [
        since.astimezone(tz).date() + timedelta(days=i)
        for i in range(1, (today - since.astimezone(tz).date()).days)
    ]
    spread = 0.0
    values = [daily.get(d, Fraction(0)) for d in days]
    if len(values) >= 2 and sum(values) > 0:
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        spread = float(pace) * math.sqrt(var) / float(mean) * math.sqrt(left)
    base = round(base_per_day * month.days) if base_per_day is not None else 0
    cents = tariff.cents(expected) + base
    low = max(spent_cents, math.floor((float(expected) - spread) / 1000) + base)
    high = math.ceil((float(expected) + spread) / 1000) + base
    return BudgetForecast(
        cents=cents,
        low_cents=min(low, cents),
        high_cents=max(high, cents),
        observed_days=int(observed),
    )


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
    pct = pct_of(total, budget.limit_cents) if budget and total is not None else None
    return BudgetStatus(
        period=period,
        budget=budget,
        spent_cents=total,
        confirmed_cents=spend.confirmed_cents if spend else None,
        shared_cents=spend.shared_cents if spend else None,
        base_cents=spend.base_cents if spend else None,
        pct=pct,
        light=budget_light(pct),
        forecast=spend.forecast if spend else None,
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
                    forecast_cents=spend.forecast.cents if spend.forecast else None,
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


def allowance_left(
    conn: sqlite3.Connection, household_id: UUID, room_id: UUID, period: str
) -> int | None:
    """Plafond solidário (BILL-03) que o quarto ainda tem no mês: o limite do mês menos o
    aquecimento provado já coberto, com a mesma regra do fecho. `None` sem plafond."""
    month = month_period(period)
    limits = room_limits(conn, household_id, month)
    if room_id not in limits:
        return None
    attributions, consumptions = period_inputs(conn, household_id, month)
    shares = [
        s
        for a in attributions
        if a.target_type is not AttributionTarget.common
        and (c := consumptions[a.consumption_event_id]).energy_wh
        for s in shares_for(a, c)
    ]
    _, covered = allowance.apply(
        shares,
        consumptions,
        tenants_in_period(conn, household_id, month),
        limits,
        heating_appliances(conn, household_id),
    )
    used = sum(wh for cid, wh in covered.items() if consumptions[cid].room_id == room_id)
    return max(0, limits[room_id] - used)
