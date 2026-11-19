"""Interfaces entre a composição da app e providers do assistente (PROPOSTA #157, item 15).

Providers síncronos: devolvem valores já calculados e não fazem escrita.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from homemind.contracts.common import Provenance


@dataclass(frozen=True)
class ToolValue:
    """Valores já calculados em código. `None` = sem medição (nunca 0)."""

    energy_wh: int | None
    cost_cents: int | None
    provenance: Provenance
    limit_cents: int | None = None
    forecast_cents: int | None = None


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


@dataclass(frozen=True)
class ApplianceValue:
    label: str
    cost_cents: int
    provenance: Provenance


class ApplianceProvider(Protocol):
    def top_appliances(
        self, household_id: UUID, resident_id: UUID, period: str, limit: int = 5
    ) -> tuple[ToolValue, list[ApplianceValue]] | None: ...


@dataclass(frozen=True)
class AttributionPartValue:
    label: str
    amount_cents: int
    provenance: Provenance


@dataclass(frozen=True)
class AttributionValue:
    total: ToolValue
    parts: tuple[AttributionPartValue, ...]
    final: bool


class AttributionExplainProvider(Protocol):
    def explain_attribution(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> AttributionValue | None: ...


@dataclass(frozen=True)
class ConfirmationValue:
    appliance_name: str | None
    estimated_cost_cents: int | None
    expires_at: datetime
    provenance: Provenance


@dataclass(frozen=True)
class ConfirmationsValue:
    count: int
    pending: tuple[ConfirmationValue, ...]


class ConfirmationsProvider(Protocol):
    def pending_confirmations(
        self, household_id: UUID, resident_id: UUID
    ) -> ConfirmationsValue: ...


REGISTRY_ATTR = "agent_providers"


@dataclass(frozen=True)
class ProviderSet:
    """Providers reais registados na composição; `None` significa ainda sem provider."""

    consumption: ConsumptionProvider | None = None
    budget: BudgetProvider | None = None
    receipt: ReceiptProvider | None = None
    appliances: ApplianceProvider | None = None
    attribution: AttributionExplainProvider | None = None
    confirmations: ConfirmationsProvider | None = None


__all__ = [
    "REGISTRY_ATTR",
    "BudgetProvider",
    "ApplianceProvider",
    "ApplianceValue",
    "AttributionExplainProvider",
    "AttributionPartValue",
    "AttributionValue",
    "ConsumptionProvider",
    "ConfirmationValue",
    "ConfirmationsProvider",
    "ConfirmationsValue",
    "ProviderSet",
    "ReceiptProvider",
    "ToolValue",
]
