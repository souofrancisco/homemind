"""Texto PT-PT determinístico a partir de resultados de ferramentas. Sem LLM, sem floats."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from homemind.contracts.agent import AgentTool, AgentToolRequest, AgentToolResult
from homemind.contracts.common import OperationStatus, Provenance, ValueKind
from homemind.features.agent.guardrails import extract_numbers

_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_KIND = {
    ValueKind.measured: "medido",
    ValueKind.estimated: "estimado",
    ValueKind.inferred: "inferido (com incerteza)",
}
_TOOL_LABEL = {
    AgentTool.consumption_summary: "Consumo",
    AgentTool.budget_status: "Orçamento",
    AgentTool.receipt: "Recibo",
}
# (chave da energia, chave do custo) em cada ferramenta.
_VALUE_KEYS = {
    AgentTool.consumption_summary: ("energia", "custo"),
    AgentTool.budget_status: ("energia", "gasto"),
    AgentTool.receipt: ("energia", "total"),
}


def format_eur(cents: int) -> str:
    """Cêntimos inteiros → «0,64 €», «1 234,56 €». Aritmética inteira."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", " ") + f",{rest:02d} €"


def format_kwh(wh: int) -> str:
    """Wh → «12,3 kWh» (1 casa, arredondamento ao par)."""
    kwh = (Decimal(wh) / Decimal(1000)).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    text = f"{kwh:,.1f}".replace(",", " ").replace(".", ",")
    return f"{text} kWh"


def format_period(period: str) -> str:
    """«2026-11» → «novembro de 2026»."""
    m = _PERIOD.match(period)
    if m is None:
        raise ValueError("período inválido")
    return f"{_MONTHS[int(m.group(2)) - 1]} de {m.group(1)}"


def provenance_label(p: Provenance) -> str:
    """«medido · REAL», «inferido (com incerteza) · SIMULADO»."""
    return f"{_KIND[p.kind]} · {'SIMULADO' if p.simulated else 'REAL'}"


@dataclass(frozen=True)
class Fact:
    """Um resultado de ferramenta já formatado: a única coisa de que a resposta pode falar."""

    tool: AgentTool
    period_label: str
    source_label: str
    values: dict[str, str]
    result_id: UUID


def fact_from(req: AgentToolRequest | None, res: AgentToolResult, period: str) -> Fact | None:
    """`None` se o resultado não trouxe valores (falha, sem dados) ou não corresponde ao pedido."""
    if res.status is not OperationStatus.succeeded or res.provenance is None:
        return None
    if req is not None and (req.tool is not res.tool or req.id != res.request_id):
        return None
    energy_key, cost_key = _VALUE_KEYS[res.tool]
    values: dict[str, str] = {}
    if res.energy_wh is not None:
        values[energy_key] = format_kwh(res.energy_wh)
    if res.cost_cents is not None:
        values[cost_key] = format_eur(res.cost_cents)
    if not values:
        return None
    return Fact(
        tool=res.tool,
        period_label=format_period(period),
        source_label=provenance_label(res.provenance),
        values=values,
        result_id=res.request_id,
    )


def render_fact(f: Fact) -> str:
    """Uma frase com período, valores, origem e incerteza."""
    values = ", ".join(f"{k} {v}" for k, v in f.values.items())
    return f"{_TOOL_LABEL[f.tool]} de {f.period_label}: {values}; origem: {f.source_label}."


def allowed_numbers(facts: list[Fact] | tuple[Fact, ...]) -> frozenset[Decimal]:
    """Números que uma resposta pode conter: os dos factos e o ano de cada período."""
    allowed: set[Decimal] = set()
    for f in facts:
        for text in (*f.values.values(), f.period_label):
            allowed.update(value for _, value in extract_numbers(text))
    return frozenset(allowed)
