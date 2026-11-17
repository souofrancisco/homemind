"""Escolha dos providers de cada ferramenta (seam para P4/P1).

Ordem, por ferramenta: o provider REAL registado em `app.state.agent_providers` (um
`ProviderSet`, lido em tempo de pedido); depois os dados SIMULADOS, só para a casa de demonstração
(`fixtures.HOUSEHOLD` com `source_kind='demo'`); senão nada (`EmptyProviders`).

Regras:
- Só se recua para o elo seguinte quando o anterior devolve `None` (sem dados). Uma exceção nunca
  recua: sobe até `ToolRegistry`, que a regista (só o tipo) e responde `provider_error`.
- Numa casa real (`source_kind != 'demo'`) um valor com proveniência simulada é descartado
  (→ sem dados): dados simulados nunca entram numa casa real, venham de onde vierem.
- O recibo é consistente: o provider que respondeu a `latest_bill` é o que responde a `receipt`.

Esta feature não importa nenhuma outra: quem regista o `ProviderSet` é a composição.
"""

import logging
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from homemind.contracts import fixtures as fx
from homemind.features.agent.providers import (
    REGISTRY_ATTR,
    BudgetProvider,
    ConsumptionProvider,
    ProviderSet,
    ReceiptProvider,
    ToolValue,
)
from homemind.features.agent.simulated import EmptyProviders, SimulatedProviders

log = logging.getLogger(__name__)

__all__ = ["RegisteredDep", "get_registered", "resolve"]


def get_registered(request: Request) -> ProviderSet:
    """Providers registados em `app.state` (vazio se nenhum, ou se o registo for de outro tipo)."""
    value = getattr(request.app.state, REGISTRY_ATTR, None)
    if value is None:
        return ProviderSet()
    if not isinstance(value, ProviderSet):
        log.warning("app.state.%s não é um ProviderSet; ignorado", REGISTRY_ATTR)
        return ProviderSet()
    return value


RegisteredDep = Annotated[ProviderSet, Depends(get_registered)]


@lru_cache
def _simulated() -> SimulatedProviders:
    return SimulatedProviders()


_EMPTY = EmptyProviders()


def _keep(value: ToolValue | None, real_house: bool) -> ToolValue | None:
    if value is not None and real_house and value.provenance.simulated:
        return None
    return value


class _ConsumptionChain:
    def __init__(self, links: list[ConsumptionProvider], real_house: bool):
        self._links, self._real = links, real_house

    def consumption_summary(
        self, household_id: UUID, resident_id: UUID, period: str
    ) -> ToolValue | None:
        for link in self._links:
            value = _keep(link.consumption_summary(household_id, resident_id, period), self._real)
            if value is not None:
                return value
        return None


class _BudgetChain:
    def __init__(self, links: list[BudgetProvider], real_house: bool):
        self._links, self._real = links, real_house

    def budget_status(self, household_id: UUID, resident_id: UUID, period: str) -> ToolValue | None:
        for link in self._links:
            value = _keep(link.budget_status(household_id, resident_id, period), self._real)
            if value is not None:
                return value
        return None


class _ReceiptChain:
    """Uma instância por pedido: lembra que elo respondeu a `latest_bill` para cada fatura."""

    def __init__(self, links: list[ReceiptProvider], real_house: bool):
        self._links, self._real = links, real_house
        self._owner: dict[UUID, ReceiptProvider] = {}

    def latest_bill(self, household_id: UUID, resident_id: UUID) -> tuple[UUID, str] | None:
        for link in self._links:
            latest = link.latest_bill(household_id, resident_id)
            if latest is not None:
                self._owner[latest[0]] = link
                return latest
        return None

    def receipt(self, household_id: UUID, resident_id: UUID, bill_id: UUID) -> ToolValue | None:
        owner = self._owner.get(bill_id)
        for link in [owner] if owner is not None else self._links:
            value = _keep(link.receipt(household_id, resident_id, bill_id), self._real)
            if value is not None:
                return value
        return None


def resolve(
    registered: ProviderSet, household_id: UUID, source_kind: str
) -> tuple[ConsumptionProvider, BudgetProvider, ReceiptProvider]:
    """Cadeias de consumo, orçamento e recibo para esta casa (ver o módulo)."""
    demo_data = household_id == fx.HOUSEHOLD and source_kind == "demo"
    real_house = source_kind != "demo"
    sim = _simulated() if demo_data else None
    consumption: list[ConsumptionProvider] = [
        p for p in (registered.consumption, sim) if p is not None
    ]
    budget: list[BudgetProvider] = [p for p in (registered.budget, sim) if p is not None]
    receipt: list[ReceiptProvider] = [p for p in (registered.receipt, sim) if p is not None]
    return (
        _ConsumptionChain(consumption or [_EMPTY], real_house),
        _BudgetChain(budget or [_EMPTY], real_house),
        _ReceiptChain(receipt or [_EMPTY], real_house),
    )
