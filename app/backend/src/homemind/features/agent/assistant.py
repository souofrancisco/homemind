"""Ciclo do assistente: pergunta → (ferramentas) → resposta validada, com fallback determinístico.

O LLM só redige. Todos os números da resposta têm de vir de resultados de ferramentas; senão
há uma correção e, depois, o fallback. Só leitura; sem LLM o assistente continua útil.
"""

import asyncio
import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from homemind.contracts.agent import AgentTool
from homemind.contracts.household import MembershipRole
from homemind.features.agent.formatting import (
    Fact,
    allowed_numbers,
    fact_from,
    format_period,
    render_fact,
)
from homemind.features.agent.guardrails import invented_numbers, is_action_request
from homemind.features.agent.llm import Complete, extract_json
from homemind.features.agent.prompt import (
    build_system_prompt,
    error_message,
    facts_message,
    no_data_message,
)
from homemind.features.agent.tools import ToolCall, ToolContext, ToolRegistry, ToolRejected

log = logging.getLogger(__name__)

MAX_TEXT = 2000
HISTORY_LIMIT = 6
_RAW_ECHO = 1000  # máximo de uma resposta do modelo repetida na conversa

LANDLORD_TEXT = (
    "O assistente de consumo é só para moradores. Como senhorio, consultas na aplicação os "
    "totais mensais por quarto e os alertas."
)
ACTION_TEXT = (
    "Ainda não executo ações (ligar, desligar, alarmes ou cenários). Posso explicar o teu "
    "consumo, o teu orçamento e o teu recibo."
)
UNAVAILABLE_PREFIX = "O assistente está indisponível de momento; eis os dados:"
UNAVAILABLE_TEXT = (
    "O assistente está indisponível de momento. O orçamento e os recibos continuam na app."
)


class _Degrade(Exception):
    """Sinal interno do ciclo: usar a resposta de recurso com este motivo (fora do prazo)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AssistantReply:
    text: str
    facts: tuple[Fact, ...]
    tool_result_ids: tuple
    used_llm: bool
    degraded_reason: (
        str | None
    )  # llm_unavailable | llm_invalid | numbers_not_grounded | max_steps | timeout


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_INTENTS = (
    (AgentTool.budget_status, re.compile(r"orcamento")),
    (AgentTool.receipt, re.compile(r"recibo|fatura|pago mais|paguei mais")),
    (AgentTool.consumption_summary, re.compile(r"consumo|consumi|gastei|gasto|kwh")),
)


def route_intent(text: str) -> AgentTool | None:
    plain = _plain(text)
    for tool, pattern in _INTENTS:
        if pattern.search(plain):
            return tool
    return None


def _same(a: Fact, b: Fact) -> bool:
    return (a.tool, a.period_label, a.source_label, a.values) == (
        b.tool,
        b.period_label,
        b.source_label,
        b.values,
    )


def _fit(body: str, footer: str) -> str:
    room = MAX_TEXT - len(footer)
    if len(body) > room:
        body = body[: max(room - 1, 0)].rstrip() + "…"
    return body + footer


def _fixed(text: str) -> AssistantReply:
    return AssistantReply(text, (), (), False, None)


def fallback_reply(
    text: str, ctx: ToolContext, registry: ToolRegistry, reason: str
) -> AssistantReply:
    """Resposta sem LLM: com intenção reconhecida mostra os factos; senão remete para a app."""
    tool = route_intent(text)
    if tool is None:
        return AssistantReply(UNAVAILABLE_TEXT, (), (), False, reason)
    try:
        call = registry.call(tool.value, {}, ctx)
    except ToolRejected:  # não deve acontecer: argumentos vazios
        return AssistantReply(UNAVAILABLE_TEXT, (), (), False, reason)
    fact = fact_from(call.request, call.result, call.period)
    if fact is None:
        if tool is AgentTool.receipt:
            body = "Não tenho dados de recibos."
        else:
            body = f"Não tenho dados para {format_period(call.period)}."
        return AssistantReply(body, (), (), False, reason)
    body = _fit(f"{UNAVAILABLE_PREFIX}\n{render_fact(fact)}", "")
    return AssistantReply(body, (fact,), (fact.result_id,), False, reason)


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
        self._registry = registry
        self._complete = complete
        self._max_steps = max_steps
        self._timeout_s = timeout_s
        # Prazo da resposta inteira: nunca mais do que `max_steps` chamadas ao LLM no pior caso.
        self._deadline_s = min(timeout_s * max_steps, total_timeout_s)

    async def reply(
        self, text: str, ctx: ToolContext, history: Sequence[tuple[str, str]] = ()
    ) -> AssistantReply:
        """`history`: pares (papel, texto) com papel `user` ou `assistant`, do mais antigo."""
        text = text.strip()[:MAX_TEXT]
        if ctx.role is not MembershipRole.tenant:
            return _fixed(LANDLORD_TEXT)
        if is_action_request(text):
            return _fixed(ACTION_TEXT)
        if self._complete is None:
            return await self._fallback(text, ctx, "llm_unavailable")

        # A resposta de recurso é calculada FORA do prazo total: se fosse calculada lá dentro,
        # o prazo podia cancelá-la a meio e repeti-la com outro motivo (teste instável).
        try:
            async with asyncio.timeout(self._deadline_s):
                return await self._cycle(text, ctx, history)
        except _Degrade as d:
            reason = d.reason
        except TimeoutError:
            log.warning("Prazo total do assistente esgotado")
            reason = "timeout"
        return await self._fallback(text, ctx, reason)

    async def _cycle(
        self, text: str, ctx: ToolContext, history: Sequence[tuple[str, str]]
    ) -> AssistantReply:
        assert self._complete is not None
        messages = [{"role": "system", "content": build_system_prompt(self._registry.specs())}]
        messages += [
            {"role": role, "content": content[:MAX_TEXT]}
            for role, content in list(history)[-HISTORY_LIMIT:]
            if role in ("user", "assistant")
        ]
        messages.append({"role": "user", "content": text})

        facts: list[Fact] = []
        calls: list[ToolCall] = []
        json_corrected = numbers_corrected = False

        for _ in range(self._max_steps):
            try:
                raw = await asyncio.wait_for(self._complete(messages), self._timeout_s)
            except Exception as e:  # LLMUnavailable, timeout do passo ou erro inesperado
                log.warning("LLM indisponível (%s)", type(e).__name__)
                raise _Degrade("llm_unavailable") from None
            echo = {"role": "assistant", "content": raw[:_RAW_ECHO]}

            try:
                data = extract_json(raw)
                tool_name, answer = data.get("tool"), data.get("answer")
                if not (isinstance(tool_name, str) or (isinstance(answer, str) and answer.strip())):
                    raise ValueError("faltam 'tool' ou 'answer'")
            except ValueError:
                if json_corrected:
                    raise _Degrade("llm_invalid") from None
                json_corrected = True
                messages += [
                    echo,
                    error_message('A resposta não era um JSON válido com "tool" ou "answer".'),
                ]
                continue

            if isinstance(tool_name, str):
                args = data.get("args", {})
                try:
                    call = await asyncio.to_thread(self._registry.call, tool_name, args, ctx)
                except ToolRejected as e:
                    messages += [echo, error_message(f"{e} ({e.code}).")]
                    continue
                calls.append(call)
                fact = fact_from(call.request, call.result, call.period)
                if fact is None:
                    messages += [
                        echo,
                        no_data_message(call.result.tool.value, format_period(call.period)),
                    ]
                else:
                    if not any(_same(fact, f) for f in facts):
                        facts.append(fact)
                    messages += [echo, facts_message([fact])]
                continue

            years = {Decimal(p[:4]) for p in (ctx.period, *(c.period for c in calls))}
            allowed = allowed_numbers(facts) | years
            bad = invented_numbers(answer, allowed)
            if bad:
                if numbers_corrected:
                    raise _Degrade("numbers_not_grounded")
                numbers_corrected = True
                messages += [
                    echo,
                    error_message(
                        f"A resposta tem números que não constam dos FACTOS ({', '.join(bad)}). "
                        "Reescreve só com números dos FACTOS ou diz que não tens dados."
                    ),
                ]
                continue

            footer = ""
            if facts:
                footer = "\n\nFonte:\n" + "\n".join(f"- {render_fact(f)}" for f in facts)
            return AssistantReply(
                _fit(answer.strip(), footer),
                tuple(facts),
                tuple(f.result_id for f in facts),
                True,
                None,
            )

        raise _Degrade("max_steps")

    async def _fallback(self, text: str, ctx: ToolContext, reason: str) -> AssistantReply:
        return await asyncio.to_thread(fallback_reply, text, ctx, self._registry, reason)
