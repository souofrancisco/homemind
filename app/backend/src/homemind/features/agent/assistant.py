"""Traduz uma pergunta para ferramentas; o servidor executa-as e escreve a resposta."""

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass

from homemind.contracts.agent import AgentTool, AgentToolResult
from homemind.contracts.common import OperationStatus
from homemind.contracts.household import MembershipRole
from homemind.features.agent.answers import no_match, render
from homemind.features.agent.guardrails import is_action_request
from homemind.features.agent.llm import Complete, extract_json
from homemind.features.agent.prompt import build_system_prompt
from homemind.features.agent.tools import ToolCall, ToolContext, ToolRegistry, ToolRejected

log = logging.getLogger(__name__)
MAX_TEXT = 2000
LANDLORD_TEXT = (
    "O assistente de consumo é só para moradores. Como senhorio, consultas na aplicação os "
    "totais mensais por quarto e os alertas."
)
ACTION_TEXT = (
    "Ainda não executo ações (ligar, desligar, alarmes ou cenários). Posso explicar o teu "
    "consumo, o teu orçamento e o teu recibo."
)
UNAVAILABLE_TEXT = (
    "O assistente está indisponível de momento. O orçamento e os recibos continuam na app."
)


@dataclass(frozen=True)
class AssistantReply:
    text: str
    tool_result_ids: tuple
    used_llm: bool
    degraded_reason: str | None
    tool_results: tuple[AgentToolResult, ...] = ()


def _plain(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    )


def route_intent(text: str) -> AgentTool | None:
    p = _plain(text)
    if re.search(
        r"tenho (?:alguma )?(?:coisa|algo) para responder|tenho pedidos? por responder|"
        r"pedidos? pendentes|preciso de votar",
        p,
    ):
        return AgentTool.pending_confirmations
    if re.search(
        r"porque pago|por que pago|como (?:e que )?chegaram? a este valor|"
        r"explica (?:a )?minha parte|"
        r"porque (?:e que )?me atribuiram",
        p,
    ):
        return AgentTool.explain_attribution
    if re.search(r"aparelho|eletrodomestico|dispositivo", p) and re.search(r"mais|maior|gast", p):
        return AgentTool.top_appliances
    if re.search(r"porque|por que|subiu|aumentou|mais caro|mudou|variou", p):
        return AgentTool.consumption_change
    if "orcamento" in p:
        return AgentTool.budget_status
    if re.search(r"recibo|fatura", p):
        return AgentTool.receipt
    if re.search(r"consumo|consumi|gastei|gasto|kwh", p):
        return AgentTool.consumption_summary
    return None


def _reply(calls: list[ToolCall], used_llm: bool, reason: str | None = None) -> AssistantReply:
    return AssistantReply(
        " ".join(render(c) for c in calls) if calls else no_match(),
        tuple(c.result.request_id for c in calls if c.result.status is OperationStatus.succeeded),
        used_llm,
        reason,
        tuple(c.result for c in calls),
    )


class Assistant:
    def __init__(
        self,
        registry: ToolRegistry,
        complete: Complete | None,
        *,
        max_steps: int = 4,
        timeout_s: float = 20.0,
        total_timeout_s: float = 30.0,
    ):
        self._registry, self._complete = registry, complete
        self._timeout_s, self._deadline_s = timeout_s, min(timeout_s * max_steps, total_timeout_s)

    async def reply(self, text: str, ctx: ToolContext, history=()) -> AssistantReply:
        del history  # o histórico existe apenas para a app e nunca sai para o LLM
        text = text.strip()[:MAX_TEXT]
        if ctx.role is not MembershipRole.tenant:
            return AssistantReply(LANDLORD_TEXT, (), False, None)
        if is_action_request(text):
            return AssistantReply(ACTION_TEXT, (), False, None)
        if self._complete is None:
            return self._rules(text, ctx)
        try:
            async with asyncio.timeout(self._deadline_s):
                return await self._interpret(text, ctx)
        except TimeoutError:
            log.warning("Prazo do assistente esgotado")
            return self._failed_to_rules(text, ctx, "timeout")

    def _rules(self, text, ctx):
        tool = route_intent(text)
        if tool is None:
            return AssistantReply(no_match(), (), False, None)
        try:
            return _reply([self._registry.call(tool.value, {}, ctx)], False)
        except ToolRejected:
            return AssistantReply(no_match(), (), False, None)

    def _failed_to_rules(self, text, ctx, reason):
        r = self._rules(text, ctx)
        if r.tool_result_ids:
            return AssistantReply(
                "O assistente está indisponível de momento. " + r.text,
                r.tool_result_ids,
                False,
                reason,
            )
        return AssistantReply(UNAVAILABLE_TEXT, (), False, reason)

    async def _interpret(self, text, ctx):
        assert self._complete is not None
        messages = [
            {"role": "system", "content": build_system_prompt(self._registry.specs(), ctx.period)},
            {"role": "user", "content": text},
        ]
        data = None
        for attempt in range(2):
            try:
                raw = await asyncio.wait_for(self._complete(messages), self._timeout_s)
            except Exception as e:
                log.warning("LLM indisponível (%s)", type(e).__name__)
                return self._failed_to_rules(text, ctx, "llm_unavailable")
            try:
                parsed = extract_json(raw)
                if set(parsed) != {"tools"}:
                    raise ValueError("objeto JSON inválido")
                calls = parsed.get("tools")
                if (
                    not isinstance(calls, list)
                    or len(calls) > 3
                    or any(
                        not isinstance(c, dict)
                        or set(c) != {"tool", "args"}
                        or not isinstance(c["tool"], str)
                        or not isinstance(c["args"], dict)
                        for c in calls
                    )
                ):
                    raise ValueError("formato inválido")
                data = calls
                break
            except ValueError:
                if attempt:
                    return AssistantReply(no_match(), (), True, "llm_invalid")
                messages = [
                    messages[0],
                    messages[1],
                    {
                        "role": "user",
                        "content": (
                            'JSON inválido. Devolve apenas {"tools": []} ou JSON com ferramentas.'
                        ),
                    },
                ]
        if not data:
            return AssistantReply(no_match(), (), True, None)
        results = []
        for item in data:
            try:
                period = item["args"].get("period", ctx.period)
                if (
                    not isinstance(period, str)
                    or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period)
                    or period < "2000-01"
                    or period > ctx.period
                ):
                    return AssistantReply(no_match(), (), True, "invalid_arguments")
                results.append(self._registry.call(item["tool"], item["args"], ctx))
            except ToolRejected:
                return AssistantReply(no_match(), (), True, "invalid_arguments")
        return _reply(results, True)
