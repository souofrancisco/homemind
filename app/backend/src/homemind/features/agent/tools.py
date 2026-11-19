"""Registo de ferramentas de leitura. O residente vem sempre do contexto, nunca dos argumentos."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from homemind.contracts.agent import AgentTool, AgentToolRequest, AgentToolResult
from homemind.contracts.agent_providers import AttributionExplainProvider, ConfirmationsProvider
from homemind.contracts.common import OperationStatus, Period, Provenance
from homemind.contracts.household import MembershipRole
from homemind.features.agent.providers import (
    ApplianceProvider,
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
    ToolSpec(
        AgentTool.top_appliances,
        "Até cinco aparelhos com maior custo do próprio utilizador.",
        _PERIOD_ARG,
    ),
    ToolSpec(
        AgentTool.consumption_change, "Compara o gasto deste mês com o mês anterior.", _PERIOD_ARG
    ),
    ToolSpec(
        AgentTool.explain_attribution,
        "Explica as parcelas do próprio morador num mês; não revela presenças nem votos.",
        _PERIOD_ARG,
    ),
    ToolSpec(
        AgentTool.pending_confirmations,
        "Conta pedidos de confirmação ainda por responder pelo próprio morador.",
    ),
)
_ALLOWED_ARGS = {s.tool: frozenset(s.args) for s in _SPECS}


class ToolRegistry:
    def __init__(
        self,
        consumption: ConsumptionProvider,
        budget: BudgetProvider,
        receipt: ReceiptProvider,
        appliances: ApplianceProvider | None = None,
        attribution: AttributionExplainProvider | None = None,
        confirmations: ConfirmationsProvider | None = None,
        *,
        new_id: Callable[[], UUID] = uuid4,
    ):
        self._consumption = consumption
        self._budget = budget
        self._receipt = receipt
        self._appliances = appliances
        self._attribution = attribution
        self._confirmations = confirmations
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
        if tool is AgentTool.pending_confirmations:
            request = AgentToolRequest(id=self._new_id(), tool=tool)
        elif tool is not AgentTool.receipt:
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
        if tool is AgentTool.explain_attribution:
            if self._attribution is None:
                return self._failed(request, tool, period, "no_data")
            return self._call_attribution(request, period, ctx)
        if tool is AgentTool.pending_confirmations:
            return self._call_confirmations(request, ctx)
        if tool in (AgentTool.top_appliances, AgentTool.consumption_change):
            return self._call_extended(tool, request, period, ctx)
        assert request is not None
        read = (
            self._consumption.consumption_summary
            if tool is AgentTool.consumption_summary
            else self._budget.budget_status
        )
        return self._finish(
            request, tool, period, lambda: read(ctx.household_id, ctx.resident_id, period)
        )

    def _call_attribution(self, request, period, ctx):
        try:
            value = self._attribution.explain_attribution(ctx.household_id, ctx.resident_id, period)
            if value is None:
                return self._failed(request, AgentTool.explain_attribution, period, "no_data")
            result = AgentToolResult(
                request_id=request.id,
                tool=AgentTool.explain_attribution,
                status=OperationStatus.succeeded,
                provenance=value.total.provenance,
                cost_cents=value.total.cost_cents,
                final=value.final,
                attribution_parts=[
                    {
                        "label": part.label,
                        "amount_cents": part.amount_cents,
                        "provenance": part.provenance,
                    }
                    for part in value.parts
                ],
            )
            return ToolCall(request, result, period)
        except Exception as e:
            log.warning(
                "fornecedor de %s falhou (%s)",
                AgentTool.explain_attribution.value,
                type(e).__name__,
            )
            return self._failed(request, AgentTool.explain_attribution, period, "provider_error")

    def _call_confirmations(self, request, ctx):
        if self._confirmations is None:
            value = None
        else:
            try:
                value = self._confirmations.pending_confirmations(ctx.household_id, ctx.resident_id)
            except Exception as e:
                log.warning(
                    "fornecedor de %s falhou (%s)",
                    AgentTool.pending_confirmations.value,
                    type(e).__name__,
                )
                return self._failed(
                    request, AgentTool.pending_confirmations, ctx.period, "provider_error"
                )
        pending = value.pending if value else ()
        result = AgentToolResult(
            request_id=request.id,
            tool=AgentTool.pending_confirmations,
            status=OperationStatus.succeeded,
            provenance=(
                Provenance.combine(*(item.provenance for item in pending)) if pending else None
            ),
            pending_count=value.count if value else 0,
            pending=[
                {
                    "appliance_name": item.appliance_name,
                    "estimated_cost_cents": item.estimated_cost_cents,
                    "expires_at": item.expires_at,
                    "provenance": item.provenance,
                }
                for item in pending
            ],
        )
        return ToolCall(request, result, ctx.period)

    def _call_extended(self, tool, request, period, ctx):
        from homemind.contracts.agent import AgentToolResult
        from homemind.contracts.common import OperationStatus

        if tool is AgentTool.top_appliances:
            if self._appliances is None:
                return self._failed(request, tool, period, "no_data")
            try:
                value = self._appliances.top_appliances(
                    ctx.household_id, ctx.resident_id, period, 5
                )
                if value is None:
                    return self._failed(request, tool, period, "no_data")
                total, rows = value
                result = AgentToolResult(
                    request_id=request.id,
                    tool=tool,
                    status=OperationStatus.succeeded,
                    provenance=total.provenance,
                    cost_cents=total.cost_cents,
                    appliances=[
                        {
                            "label": r.label,
                            "cost_cents": r.cost_cents,
                            "percent": (r.cost_cents * 100 + (total.cost_cents or 0) // 2)
                            // (total.cost_cents or 1),
                            "provenance": r.provenance,
                        }
                        for r in rows
                    ],
                )
                return ToolCall(request, result, period)
            except Exception as e:
                log.warning("fornecedor de %s falhou (%s)", tool.value, type(e).__name__)
                return self._failed(request, tool, period, "provider_error")

        current = self._consumption.consumption_summary(ctx.household_id, ctx.resident_id, period)
        y, m = map(int, period.split("-"))
        previous = f"{y - (m == 1):04d}-{(m - 1 if m > 1 else 12):02d}"
        prior = self._consumption.consumption_summary(ctx.household_id, ctx.resident_id, previous)
        if (
            current is None
            or prior is None
            or current.cost_cents is None
            or prior.cost_cents is None
        ):
            return self._failed(request, tool, period, "no_data")
        rows = []
        if self._appliances:
            now_rows = self._appliances.top_appliances(ctx.household_id, ctx.resident_id, period, 5)
            old_rows = self._appliances.top_appliances(
                ctx.household_id, ctx.resident_id, previous, 5
            )
            if now_rows and old_rows:
                old = {r.label: r.cost_cents for r in old_rows[1]}
                rows = sorted(
                    (
                        (r.cost_cents - old.get(r.label, 0), r.label, r.provenance)
                        for r in now_rows[1]
                    ),
                    reverse=True,
                )
                rows = [r for r in rows if r[0] > 0][:3]
        result = AgentToolResult(
            request_id=request.id,
            tool=tool,
            status=OperationStatus.succeeded,
            provenance=Provenance.combine(current.provenance, prior.provenance),
            cost_cents=current.cost_cents,
            previous_period=previous,
            previous_cost_cents=prior.cost_cents,
            difference_cents=current.cost_cents - prior.cost_cents,
            appliances=[
                {"label": label, "cost_cents": cents, "percent": 0, "provenance": provenance}
                for cents, label, provenance in rows
            ],
        )
        return ToolCall(request, result, period)

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
