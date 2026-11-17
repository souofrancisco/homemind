"""Registo de ferramentas de leitura. O residente vem sempre do contexto, nunca dos argumentos."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from homemind.contracts.agent import AgentTool, AgentToolRequest, AgentToolResult
from homemind.contracts.common import OperationStatus, Period
from homemind.contracts.household import MembershipRole
from homemind.features.agent.providers import (
    BudgetProvider,
    ConsumptionProvider,
    ReceiptProvider,
    ToolValue,
)

log = logging.getLogger(__name__)

_PERIOD = TypeAdapter(Period)


@dataclass(frozen=True)
class ToolContext:
    household_id: UUID
    resident_id: UUID
    role: MembershipRole
    now: datetime
    period: str  # mês por omissão, `YYYY-MM`


class ToolRejected(ValueError):
    """Pedido de ferramenta inválido (volta ao modelo como erro, não como dados)."""

    def __init__(self, code: Literal["unknown_tool", "invalid_arguments"], message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolSpec:
    tool: AgentTool
    description: str
    args: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    """`request` é `None` quando nem chegou a haver pedido válido (recibo sem fatura, papel)."""

    request: AgentToolRequest | None
    result: AgentToolResult
    period: str


_PERIOD_ARG = {"period": "mês no formato AAAA-MM; se omitido, o mês atual"}
_SPECS = (
    ToolSpec(
        AgentTool.consumption_summary,
        "Consumo (energia e custo) do próprio utilizador num mês.",
        _PERIOD_ARG,
    ),
    ToolSpec(
        AgentTool.budget_status,
        "Quanto o utilizador já gastou do seu orçamento num mês.",
        _PERIOD_ARG,
    ),
    ToolSpec(AgentTool.receipt, "Total do recibo mais recente do utilizador."),
)
_ALLOWED_ARGS = {s.tool: frozenset(s.args) for s in _SPECS}


class ToolRegistry:
    def __init__(
        self,
        consumption: ConsumptionProvider,
        budget: BudgetProvider,
        receipt: ReceiptProvider,
        *,
        new_id: Callable[[], UUID] = uuid4,
    ):
        self._consumption = consumption
        self._budget = budget
        self._receipt = receipt
        self._new_id = new_id

    def specs(self) -> list[ToolSpec]:
        return list(_SPECS)

    def call(self, name: str, args: dict, ctx: ToolContext) -> ToolCall:
        tool = self._parse_tool(name)
        if not isinstance(args, dict):
            raise ToolRejected("invalid_arguments", "os argumentos têm de ser um objeto")
        extra = sorted(str(k)[:40] for k in args if k not in _ALLOWED_ARGS[tool])
        if extra:
            raise ToolRejected("invalid_arguments", f"argumentos não permitidos: {extra}")

        period = ctx.period
        request: AgentToolRequest | None = None
        if tool is not AgentTool.receipt:
            period = args.get("period") or ctx.period
            try:
                request = AgentToolRequest(id=self._new_id(), tool=tool, period=period)
            except ValidationError:
                raise ToolRejected("invalid_arguments", "período inválido (usa AAAA-MM)") from None

        # Só moradores: sem dados individuais para senhorio/operador (e sem chamar fornecedores).
        if ctx.role is not MembershipRole.tenant:
            return self._failed(request, tool, period, "forbidden_role")

        if tool is AgentTool.receipt:
            return self._call_receipt(ctx)
        assert request is not None
        read = (
            self._consumption.consumption_summary
            if tool is AgentTool.consumption_summary
            else self._budget.budget_status
        )
        return self._finish(
            request, tool, period, lambda: read(ctx.household_id, ctx.resident_id, period)
        )

    # -- internos ---------------------------------------------------------------------------

    @staticmethod
    def _parse_tool(name: object) -> AgentTool:
        try:
            return AgentTool(name)
        except ValueError:
            raise ToolRejected("unknown_tool", "ferramenta desconhecida") from None

    def _call_receipt(self, ctx: ToolContext) -> ToolCall:
        try:
            latest = self._receipt.latest_bill(ctx.household_id, ctx.resident_id)
            if latest is None:
                return self._failed(None, AgentTool.receipt, ctx.period, "no_data")
            bill_id, bill_period = latest
            period = _PERIOD.validate_python(bill_period)
            request = AgentToolRequest(id=self._new_id(), tool=AgentTool.receipt, bill_id=bill_id)
        except Exception as e:  # fornecedor com defeito: só o tipo no log
            log.warning("fornecedor de recibos falhou (%s)", type(e).__name__)
            return self._failed(None, AgentTool.receipt, ctx.period, "provider_error")
        return self._finish(
            request,
            AgentTool.receipt,
            period,
            lambda: self._receipt.receipt(ctx.household_id, ctx.resident_id, bill_id),
        )

    def _finish(
        self,
        request: AgentToolRequest,
        tool: AgentTool,
        period: str,
        fetch: Callable[[], ToolValue | None],
    ) -> ToolCall:
        try:
            value = fetch()
            if value is None or (value.energy_wh is None and value.cost_cents is None):
                return self._failed(request, tool, period, "no_data")
            result = AgentToolResult(
                request_id=request.id,
                tool=tool,
                status=OperationStatus.succeeded,
                provenance=value.provenance,
                energy_wh=value.energy_wh,
                cost_cents=value.cost_cents,
            )
        except Exception as e:  # só o tipo: a mensagem pode ter dados ou segredos
            log.warning("fornecedor de %s falhou (%s)", tool.value, type(e).__name__)
            return self._failed(request, tool, period, "provider_error")
        return ToolCall(request, result, period)

    def _failed(
        self, request: AgentToolRequest | None, tool: AgentTool, period: str, code: str
    ) -> ToolCall:
        result = AgentToolResult(
            request_id=request.id if request else self._new_id(),
            tool=tool,
            status=OperationStatus.failed,
            error_code=code,
        )
        return ToolCall(request, result, period)
