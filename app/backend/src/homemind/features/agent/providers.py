"""Fontes de dados das ferramentas.

PROPOSTA: interface a mover para contracts/agent.py (revisão #73). Hoje só os testes as
implementam; as reais virão de P4 (consumo, orçamento, recibos) e P1 (energia), sem a feature
importar outra: registam-se no arranque (ver `ProviderSet` e `REGISTRY_ATTR`).
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from homemind.contracts.common import Provenance


@dataclass(frozen=True)
class ToolValue:
    """Valores já calculados em código. `None` = sem medição (nunca 0)."""

    energy_wh: int | None
    cost_cents: int | None
    provenance: Provenance


class ConsumptionProvider(Protocol):
    def consumption_summary(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> ToolValue | None: ...


class BudgetProvider(Protocol):
    def budget_status(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> ToolValue | None: ...


class ReceiptProvider(Protocol):
    def receipt(self, household_id: UUID, resident_id: UUID, bill_id: UUID) -> ToolValue | None: ...

    def latest_bill(self, household_id: UUID, resident_id: UUID) -> tuple[UUID, str] | None:
        """(bill_id, período `YYYY-MM`) do recibo mais recente do residente."""
        ...


# PROPOSTA (#157 item 15): nome do atributo de `app.state` onde a composição (P4/P1) regista o
# `ProviderSet`. Lido em tempo de pedido por `sources.get_registered`, não no arranque.
REGISTRY_ATTR = "agent_providers"


@dataclass(frozen=True)
class ProviderSet:
    """Providers reais registados na composição. Cada ferramenta é independente; `None` = ainda
    não há provider real para ela (a cadeia de `sources.py` decide o que serve nesse caso)."""

    consumption: ConsumptionProvider | None = None
    budget: BudgetProvider | None = None
    receipt: ReceiptProvider | None = None


__all__ = [
    "REGISTRY_ATTR",
    "BudgetProvider",
    "ConsumptionProvider",
    "ProviderSet",
    "ReceiptProvider",
    "ToolValue",
]
