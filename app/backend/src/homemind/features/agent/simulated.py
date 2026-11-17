"""Fontes de dados SIMULADAS do assistente. SIMULADO — substituir por providers de P4/P1.

Os valores vêm de `contracts/fixtures.py` (a casa de demonstração); esta feature não escreve
nenhum número. Só servem a casa `fixtures.HOUSEHOLD` com `source_kind='demo'` (ver `router.py`);
qualquer outra casa, período ou residente fica sem dados (`None`, nunca zero) e o assistente diz
que não sabe. Toda a proveniência vem marcada como simulada.
"""

from uuid import UUID

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BillAllocation, ElectricityBill
from homemind.contracts.common import Provenance
from homemind.features.agent.providers import ToolValue

__all__ = ["EmptyProviders", "SimulatedProviders"]


def _month(bill: ElectricityBill) -> str:
    return bill.period.start.strftime("%Y-%m")


class EmptyProviders:
    """Sem dados para ninguém: as três ferramentas devolvem sempre `None`."""

    def consumption_summary(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> ToolValue | None:
        return None

    def budget_status(self, household_id: UUID, resident_id: UUID, period: str) -> ToolValue | None:
        return None

    def receipt(self, household_id: UUID, resident_id: UUID, bill_id: UUID) -> ToolValue | None:
        return None

    def latest_bill(self, household_id: UUID, resident_id: UUID) -> tuple[UUID, str] | None:
        return None


class SimulatedProviders:
    """Consumo, orçamento e recibo da casa de demonstração, derivados das fixtures."""

    def __init__(self) -> None:
        self._bill, allocations = fx.bill_a()
        self._allocations: dict[UUID, BillAllocation] = {a.resident_id: a for a in allocations}
        self._budget = fx.budget()
        # O gasto do orçamento vem da amostra do evento de limiar da própria fixture.
        self._threshold = next(
            e
            for e in fx.event_samples()
            if e.type == "alerts.threshold_crossed" and e.data.budget_id == self._budget.id
        )

    def _mine(self, household_id: UUID, resident_id: UUID) -> BillAllocation | None:
        if household_id != fx.HOUSEHOLD:
            return None
        return self._allocations.get(resident_id)

    def consumption_summary(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> ToolValue | None:
        alloc = self._mine(household_id, resident_id)
        if alloc is None or period != _month(self._bill):
            return None
        return ToolValue(
            energy_wh=alloc.attributed_total_wh,
            cost_cents=alloc.individual_cents,
            provenance=Provenance.combine(*(t.provenance for t in alloc.attributed_wh)),
        )

    def budget_status(self, household_id: UUID, resident_id: UUID, period: str) -> ToolValue | None:
        if household_id != fx.HOUSEHOLD or resident_id != self._budget.resident_id:
            return None
        if period != self._budget.period:
            return None
        return ToolValue(
            energy_wh=None,
            cost_cents=self._threshold.data.spent_cents,
            provenance=self._threshold.provenance,
        )

    def receipt(self, household_id: UUID, resident_id: UUID, bill_id: UUID) -> ToolValue | None:
        alloc = self._mine(household_id, resident_id)
        if alloc is None or bill_id != self._bill.id:
            return None
        lines = (line.provenance for line in alloc.breakdown if line.provenance is not None)
        return ToolValue(
            energy_wh=None,
            cost_cents=alloc.amount_cents,
            provenance=Provenance.combine(self._bill.provenance, *lines),
        )

    def latest_bill(self, household_id: UUID, resident_id: UUID) -> tuple[UUID, str] | None:
        if self._mine(household_id, resident_id) is None:
            return None
        return self._bill.id, _month(self._bill)
