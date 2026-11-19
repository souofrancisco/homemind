"""Respostas curtas e determinísticas a partir dos resultados tipados das ferramentas."""

from zoneinfo import ZoneInfo

from homemind.contracts.agent import AgentTool
from homemind.features.agent.formatting import (
    format_eur,
    format_kwh,
    format_period,
    provenance_label,
)
from homemind.features.agent.tools import ToolCall


def render(call: ToolCall) -> str:
    result = call.result
    if result.status.value != "succeeded":
        if result.tool is AgentTool.consumption_change and result.error_code == "no_data":
            return f"Não há dados de {format_period(call.period)} ou do mês anterior para comparar."
        return f"Não tenho dados para {format_period(call.period)}."
    if result.tool is AgentTool.explain_attribution:
        if result.cost_cents is None or not result.attribution_parts:
            return f"Não tenho dados para {format_period(call.period)}."
        parts = ", ".join(
            f"{format_eur(part.amount_cents)} {part.label.lower()}"
            for part in result.attribution_parts
        )
        label = provenance_label(result.provenance)
        state = "" if result.final else ", provisório"
        contest = " Se não concordas, podes contestar no recibo." if result.final else ""
        return (
            f"Em {format_period(call.period)} pagas {format_eur(result.cost_cents)}: {parts} "
            f"({label}{state}).{contest}"
        )
    if result.tool is AgentTool.pending_confirmations:
        count = result.pending_count or 0
        if count == 0:
            return "Não tens nenhum pedido à espera da tua resposta."
        entries = []
        for item in result.pending[:3]:
            name = item.appliance_name or "um aparelho"
            cost = (
                f" (cerca de {format_eur(item.estimated_cost_cents)})"
                if item.estimated_cost_cents is not None
                else ""
            )
            until = item.expires_at.astimezone(ZoneInfo("Europe/Lisbon"))
            entries.append(f"{name}{cost}, até {until:%d/%m %H:%M}")
        if entries:
            label = f" ({provenance_label(result.provenance)})" if result.provenance else ""
            items = "; ".join(entries)
            noun = "pedido" if count == 1 else "pedidos"
            return f"Tens {count} {noun} à espera da tua resposta: {items}.{label}"
        return f"Tens {count} pedidos à espera da tua resposta."
    label = provenance_label(result.provenance)
    if result.tool is AgentTool.top_appliances:
        rows = sorted(result.appliances, key=lambda row: (-row.cost_cents, row.label))[:2]
        if not rows:
            return f"Não tenho dados por aparelho para {format_period(call.period)}."
        items = "; a seguir, ".join(
            f"{row.label}: {format_eur(row.cost_cents)} ({row.percent} %)" for row in rows
        )
        return f"Em {format_period(call.period)} o que mais pesou foi {items}. ({label})"
    if result.tool is AgentTool.consumption_change:
        assert result.previous_period is not None and result.previous_cost_cents is not None
        assert result.difference_cents is not None
        diff = result.difference_cents
        movement = "mais" if diff >= 0 else "menos"
        text = (
            f"Em {format_period(call.period)} gastaste {movement} {format_eur(abs(diff))} "
            "do que em "
            f"{format_period(result.previous_period)}"
        )
        if result.appliances:
            details = "; ".join(
                f"+{format_eur(r.cost_cents)} do {r.label}" for r in result.appliances
            )
            text += f": {details}"
        return f"{text}. ({label})"
    cost = result.cost_cents
    if cost is None:
        return f"Não tenho dados para {format_period(call.period)}."
    if result.tool is AgentTool.budget_status:
        subject = "do teu orçamento"
    elif result.tool is AgentTool.receipt:
        subject = "no teu recibo"
    else:
        subject = ""
    middle = f" {subject}" if subject else ""
    if result.tool is AgentTool.consumption_summary and result.energy_wh is not None:
        return (
            f"Em {format_period(call.period)} consumiste {format_kwh(result.energy_wh)} "
            f"e gastaste {format_eur(cost)} ({label})."
        )
    return f"Em {format_period(call.period)} gastaste {format_eur(cost)}{middle} ({label})."


def no_match() -> str:
    return (
        "Não sei responder a isso. Posso dizer-te quanto gastaste, como vai o orçamento, o teu "
        "recibo, que aparelho gastou mais, porque pagas este valor e se tens pedidos por responder."
    )
