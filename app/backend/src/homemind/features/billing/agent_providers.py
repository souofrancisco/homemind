"""Providers de leitura do assistente construídos sobre os cálculos de faturação existentes."""

import sqlite3
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from homemind.contracts.agent_providers import (
    ApplianceValue,
    AttributionPartValue,
    AttributionValue,
    ToolValue,
)
from homemind.contracts.billing import AttributionTarget, BillAllocation, BreakdownKind
from homemind.contracts.common import Provenance
from homemind.core.db import Database
from homemind.features.billing import allowance, bills, budgets, closing, explanation, tariff
from homemind.features.billing.allocation import EnergyShare, draw_order, largest_remainder


class BillingAgentProviders:
    """Acesso curto e serializado à SQLite; cada operação só executa SELECTs.

    Os Protocols do agente são síncronos e chamados no event loop. A ligação partilhada é
    protegida pelo lock da Database para não concorrer com outras operações nem abrir uma
    transação de escrita `BEGIN IMMEDIATE`. As funções determinísticas de billing recebem essa
    ligação e o resultado não escapa do pedido.
    """

    def __init__(self, db: Database, clock: Callable[[], datetime]):
        self._db = db
        self._clock = clock

    def _read(self, fn):
        with self._db._lock:
            conn = self._db._conn
            if conn is None:
                return None
            conn.execute("PRAGMA query_only=ON")
            try:
                return fn(conn)
            finally:
                conn.execute("PRAGMA query_only=OFF")

    def consumption_summary(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> ToolValue | None:
        def read(conn: sqlite3.Connection) -> ToolValue | None:
            # Mesma fonte do orçamento: o que o morador paga inclui a sua parte das zonas
            # comuns e da base. Somar só as atribuições diretas dava um valor menor e diferente.
            spend = budgets.month_spend(conn, household_id, resident_id, period, self._clock())
            if spend is None:
                return None
            _, consumptions = closing.period_inputs(
                conn, household_id, budgets.month_period(period)
            )
            if not spend.final and not consumptions:
                return None  # sem consumos nem fecho: desconhecido, nunca 0 €
            # Sem energia: só existe a direta, e juntá-la a um custo total enganaria.
            return ToolValue(
                energy_wh=None, cost_cents=spend.total_cents, provenance=spend.provenance
            )

        return self._read(read)

    def budget_status(self, household_id: UUID, resident_id: UUID, period: str) -> ToolValue | None:
        def read(conn: sqlite3.Connection) -> ToolValue | None:
            _, consumptions = closing.period_inputs(
                conn, household_id, budgets.month_period(period)
            )
            status = budgets.status(conn, household_id, resident_id, period, self._clock())
            if status.budget is None and not status.final and not consumptions:
                return None
            if status.spent_cents is None or status.provenance is None:
                return None
            return ToolValue(
                energy_wh=None,
                cost_cents=status.spent_cents,
                provenance=status.provenance,
                limit_cents=status.budget.limit_cents if status.budget else None,
                forecast_cents=status.forecast.cents if status.forecast else None,
            )

        return self._read(read)

    def latest_bill(self, household_id: UUID, resident_id: UUID) -> tuple[UUID, str] | None:
        def read(conn: sqlite3.Connection):
            row = conn.execute(
                "SELECT b.id, b.period_start FROM billing_bill b"
                " JOIN billing_allocation a ON a.bill_id=b.id"
                " WHERE b.household_id=? AND b.status='finalized' AND a.resident_id=?"
                " ORDER BY b.period_start DESC, b.revision DESC LIMIT 1",
                (str(household_id), str(resident_id)),
            ).fetchone()
            return (UUID(row["id"]), row["period_start"][:7]) if row else None

        return self._read(read)

    def receipt(self, household_id: UUID, resident_id: UUID, bill_id: UUID) -> ToolValue | None:
        def read(conn: sqlite3.Connection) -> ToolValue | None:
            row = conn.execute(
                "SELECT b.* FROM billing_bill b JOIN billing_allocation a ON a.bill_id=b.id"
                " WHERE b.id=? AND b.household_id=? AND b.status='finalized' AND a.resident_id=?",
                (str(bill_id), str(household_id), str(resident_id)),
            ).fetchone()
            if row is None:
                return None
            allocation_row = conn.execute(
                "SELECT json FROM billing_allocation WHERE bill_id=? AND resident_id=?",
                (str(bill_id), str(resident_id)),
            ).fetchone()
            allocation = BillAllocation.model_validate_json(allocation_row["json"])
            view = bills.to_view(row)
            parts = [line.provenance for line in allocation.breakdown if line.provenance]
            provenance = Provenance.combine(view.provenance, *parts) if parts else view.provenance
            return ToolValue(
                energy_wh=None, cost_cents=allocation.amount_cents, provenance=provenance
            )

        return self._read(read)

    def explain_attribution(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> AttributionValue | None:
        """Explica apenas a parcela do residente, usando recibo ou estimativa de billing."""

        def read(conn: sqlite3.Connection) -> AttributionValue | None:
            spend = budgets.month_spend(conn, household_id, resident_id, period, self._clock())
            if spend is None:
                return None
            if spend.final:
                final = budgets._final_allocation(
                    conn, household_id, resident_id, budgets.month_period(period)
                )
                if final is None:
                    return None
                allocation, _simulated = final
                bill_row = conn.execute(
                    "SELECT * FROM billing_bill WHERE id = ?", (str(allocation.bill_id),)
                ).fetchone()
                if bill_row is None:
                    return None
                detail = explanation.explain(conn, bill_row, allocation)
                parts: list[AttributionPartValue] = []
                own_parts: dict[str, tuple[int, Provenance]] = {}
                for row in detail.own:
                    device = (
                        f"«{row.appliance_name}»"
                        if row.appliance_name
                        else "Consumo não identificado"
                    )
                    reason = (
                        " (atribuído pela votação)" if row.method.value == "confirmation" else ""
                    )
                    label = f"{device}{reason}"
                    before = own_parts.get(label)
                    own_parts[label] = (
                        row.amount_cents + (before[0] if before else 0),
                        Provenance.combine(before[1], row.provenance) if before else row.provenance,
                    )
                for label, (amount, provenance) in sorted(own_parts.items()):
                    if amount:
                        parts.append(AttributionPartValue(label, amount, provenance))
                common = sum(row.amount_cents for row in detail.common)
                if common:
                    common_provenance = Provenance.combine(
                        *(row.provenance for row in detail.common)
                    )
                    parts.append(
                        AttributionPartValue(
                            "Zonas comuns divididas por todos", common, common_provenance
                        )
                    )
                allowance_cents = detail.allowance.amount_cents if detail.allowance else 0
                line_provenance = {
                    line.kind: line.provenance
                    for line in allocation.breakdown
                    if line.provenance is not None
                }
                if allowance_cents:
                    parts.append(
                        AttributionPartValue(
                            "Plafond solidário",
                            allowance_cents,
                            line_provenance.get(BreakdownKind.heating_allowance, spend.provenance),
                        )
                    )
                if detail.fixed_cents:
                    parts.append(
                        AttributionPartValue(
                            "Parte fixa",
                            detail.fixed_cents,
                            line_provenance.get(BreakdownKind.fixed_share, spend.provenance),
                        )
                    )
                if detail.residual.amount_cents:
                    parts.append(
                        AttributionPartValue(
                            "Resíduo da fatura",
                            detail.residual.amount_cents,
                            detail.residual.provenance,
                        )
                    )
                # Uma linha adjustment pode existir em recibos corrigidos; mantém-se o total
                # explicável sem inventar uma categoria para ela.
                remainder = spend.total_cents - sum(p.amount_cents for p in parts)
                if remainder:
                    parts.append(
                        AttributionPartValue(
                            "Ajuste do recibo",
                            remainder,
                            line_provenance.get(BreakdownKind.adjustment, spend.provenance),
                        )
                    )
                if sum(p.amount_cents for p in parts) != spend.total_cents:
                    return None
                provenances = [part.provenance for part in parts] or [spend.provenance]
                total_provenance = Provenance.combine(spend.provenance, *provenances)
                return AttributionValue(
                    ToolValue(None, spend.total_cents, total_provenance), tuple(parts), True
                )

            parts = []
            for label, amount in (
                ("Consumo atribuído a ti", spend.confirmed_cents),
                ("Zonas comuns divididas por todos", spend.shared_cents),
                ("Parte fixa estimada", spend.base_cents or 0),
            ):
                if amount:
                    parts.append(AttributionPartValue(label, amount, spend.provenance))
            if not parts or sum(p.amount_cents for p in parts) != spend.total_cents:
                return None
            return AttributionValue(
                ToolValue(None, spend.total_cents, spend.provenance), tuple(parts), False
            )

        return self._read(read)

    def top_appliances(self, household_id: UUID, resident_id: UUID, period: str, limit: int = 5):
        """Custo próprio por aparelho, reconciliado ao mesmo total do orçamento mensal."""
        limit = min(5, max(1, limit))

        def read(conn: sqlite3.Connection):
            spend = budgets.month_spend(conn, household_id, resident_id, period, self._clock())
            if spend is None:
                return None
            _, period_consumptions = closing.period_inputs(
                conn, household_id, budgets.month_period(period)
            )
            if not spend.final and not period_consumptions:
                return None
            month = budgets.month_period(period)
            final = budgets._final_allocation(conn, household_id, resident_id, month)
            if final is not None:
                allocation, simulated = final
                row = conn.execute(
                    "SELECT * FROM billing_bill WHERE id = ?", (str(allocation.bill_id),)
                ).fetchone()
                bill = closing._model(row)
                everyone = closing.allocations_of(conn, bill.id)
                items = explanation._items(conn, bill.id)
                ids = sorted(a.resident_id for a in everyone)
                try:
                    own, common, pooled = explanation._reconcile(
                        allocation, items, ids, dict.fromkeys(ids, 1), draw_order(bill)
                    )
                except explanation._Mismatch:
                    return None
                totals: dict[str, int] = {}
                prov: dict[str, Provenance] = {}

                def add(item, cents):
                    c = item.consumption
                    aid = c.match.appliance_id
                    label = (
                        self._appliance_name(conn, household_id, aid)
                        if aid
                        else "Consumos não identificados"
                    )
                    if label is None:
                        label = "Consumos não identificados"
                    totals[label] = totals.get(label, 0) + cents
                    prov[label] = (
                        Provenance.combine(prov[label], c.provenance)
                        if label in prov
                        else c.provenance
                    )

                for item, cents in own.values():
                    add(item, cents)
                for item, _wh, cents in common.values():
                    add(item, cents)
                for item, _wh, cents in pooled.values():
                    add(item, cents)
                for line in allocation.breakdown:
                    if line.kind in (
                        BreakdownKind.fixed_share,
                        BreakdownKind.residual_share,
                        BreakdownKind.adjustment,
                    ):
                        label = (
                            "Parte fixa e base"
                            if line.kind is BreakdownKind.fixed_share
                            else "Consumos não identificados"
                        )
                        totals[label] = totals.get(label, 0) + line.amount_cents
                        if line.provenance:
                            prov[label] = (
                                Provenance.combine(prov[label], line.provenance)
                                if label in prov
                                else line.provenance
                            )
                provenance = spend.provenance
            else:
                computed = self._live_appliance_costs(
                    conn, household_id, resident_id, period, spend
                )
                if computed is None:
                    return None
                totals, prov = computed
                provenance = spend.provenance
            # Evidência incompleta não pode originar uma repartição que não reconcilia.
            if sum(totals.values()) != spend.total_cents:
                return None
            entries = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
            if len(entries) > limit:
                kept = entries[: limit - 1]
                kept.append(("Outros consumos", sum(v for _, v in entries[limit - 1 :])))
                entries = kept
            rows = [
                ApplianceValue(label=k, cost_cents=v, provenance=prov.get(k, provenance))
                for k, v in entries
                if v != 0
            ]
            value = ToolValue(None, spend.total_cents, provenance)
            return value, rows

        return self._read(read)

    @staticmethod
    def _appliance_name(conn, household_id, appliance_id):
        if appliance_id is None:
            return None
        row = conn.execute(
            "SELECT name FROM appliance WHERE household_id=? AND id=?",
            (str(household_id), str(appliance_id)),
        ).fetchone()
        return row["name"] if row else None

    def _live_appliance_costs(self, conn, household_id, resident_id, period, spend):
        rate = tariff.load(conn, household_id).tariff
        if rate is None:
            return None
        month = budgets.month_period(period)
        attributions, consumptions = closing.period_inputs(conn, household_id, month)
        tenants = closing.tenants_in_period(conn, household_id, month)
        if resident_id not in tenants:
            return None
        tz = budgets.household_tz(conn, household_id)
        shares, provenance = [], {}
        for a in attributions:
            c = consumptions[a.consumption_event_id]
            if not c.energy_wh:
                continue
            target = a.target_resident_id if a.target_type is AttributionTarget.resident else None
            shares.append(EnergyShare(target, c.energy_wh, c.provenance, c.id))
            provenance[c.id] = c.provenance
        adjusted, _ = allowance.apply(
            shares,
            consumptions,
            tenants,
            closing.room_limits(conn, household_id, month),
            closing.heating_appliances(conn, household_id),
        )
        mine = []
        common = []
        for share in adjusted:
            c = consumptions[share.consumption_id]
            value = tariff.value_millicents(rate, tz, share.energy_wh, c.started_at, c.ended_at)
            if share.resident_id == resident_id:
                mine.append((share, value))
            elif share.resident_id is None:
                common.append((share, value / len(tenants)))
        result = {}
        for pairs, total in ((mine, spend.confirmed_cents), (common, spend.shared_cents)):
            weights = {index: value for index, (_share, value) in enumerate(pairs)}
            cents = largest_remainder(total, weights) if weights else {}
            for index, (s, _) in enumerate(pairs):
                c = consumptions[s.consumption_id]
                name = (
                    self._appliance_name(conn, household_id, c.match.appliance_id)
                    or "Consumos não identificados"
                )
                result[name] = result.get(name, 0) + cents[index]
        result["Parte fixa e base"] = spend.base_cents or 0
        prov = {name: spend.provenance for name in result}
        return result, prov


__all__ = ["BillingAgentProviders"]
