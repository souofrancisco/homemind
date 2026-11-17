"""Fakes do assistente: LLM com guião e fornecedores com valores fixos (novembro de 2026)."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.household import MembershipRole
from homemind.features.agent.providers import ToolValue
from homemind.features.agent.tools import ToolContext

HOUSEHOLD = UUID("11111111-1111-4111-8111-111111111111")
RESIDENT = UUID("22222222-2222-4222-8222-222222222222")
OTHER_RESIDENT = UUID("33333333-3333-4333-8333-333333333333")
BILL = UUID("44444444-4444-4444-8444-444444444444")
PERIOD = "2026-11"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

SIMULATED_INFERRED = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
SIMULATED_MEASURED = Provenance(origin=Origin.simulated, kind=ValueKind.measured)
SIMULATED_ESTIMATED = Provenance(origin=Origin.simulated, kind=ValueKind.estimated)


def ctx(role: str = "tenant", period: str = PERIOD) -> ToolContext:
    return ToolContext(
        household_id=HOUSEHOLD,
        resident_id=RESIDENT,
        role=MembershipRole(role),
        now=NOW,
        period=period,
    )


class FakeLLM:
    """Responde pela ordem do guião; uma `Exception` no guião é levantada. Regista mensagens."""

    def __init__(self, script: list[str | Exception], delay_s: float = 0):
        self.script = list(script)
        self.delay_s = delay_s
        self.calls: list[list[dict[str, str]]] = []

    async def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(m) for m in messages])
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if not self.script:
            raise AssertionError("guião do FakeLLM esgotado")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeConsumption:
    def __init__(self):
        self.calls = 0

    def consumption_summary(self, household_id, resident_id, period):
        self.calls += 1
        if period != PERIOD:
            return None
        return ToolValue(energy_wh=12_340, cost_cents=2_345, provenance=SIMULATED_INFERRED)


class FakeBudget:
    def __init__(self):
        self.calls = 0

    def budget_status(self, household_id, resident_id, period):
        self.calls += 1
        if period != PERIOD:
            return None
        return ToolValue(energy_wh=None, cost_cents=6_400, provenance=SIMULATED_MEASURED)


class FakeReceipt:
    def __init__(self):
        self.calls = 0

    def receipt(self, household_id, resident_id, bill_id):
        self.calls += 1
        if bill_id != BILL:
            return None
        return ToolValue(energy_wh=98_700, cost_cents=18_750, provenance=SIMULATED_ESTIMATED)

    def latest_bill(self, household_id, resident_id):
        self.calls += 1
        return BILL, PERIOD


class EmptyConsumption:
    def consumption_summary(self, household_id, resident_id, period):
        return None


class EmptyBudget:
    def budget_status(self, household_id, resident_id, period):
        return None


class EmptyReceipt:
    def receipt(self, household_id, resident_id, bill_id):
        return None

    def latest_bill(self, household_id, resident_id):
        return None


class SpyProvider:
    """Os três fornecedores num só, a contar chamadas."""

    def __init__(self, error: Exception | None = None):
        self.calls = 0
        self.error = error

    def _hit(self):
        self.calls += 1
        if self.error:
            raise self.error
        return ToolValue(energy_wh=1_000, cost_cents=100, provenance=SIMULATED_MEASURED)

    def consumption_summary(self, household_id, resident_id, period):
        return self._hit()

    def budget_status(self, household_id, resident_id, period):
        return self._hit()

    def receipt(self, household_id, resident_id, bill_id):
        return self._hit()

    def latest_bill(self, household_id, resident_id):
        self.calls += 1
        return BILL, PERIOD
