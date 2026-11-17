"""Cliente NVIDIA (API compatível com OpenAI) e extração de JSON. Nunca atua.

Adaptado de `features/engine/llm.py::cliente_nvidia` (uma feature não importa outra). O modelo
só recebe texto: nunca imagens, frames nem segredos.
"""

import json
from collections.abc import Awaitable, Callable

from homemind.features.agent.config import AgentSettings

Complete = Callable[[list[dict[str, str]]], Awaitable[str]]


class LLMUnavailable(Exception):
    """Sem chave, sem rede ou erro do fornecedor. A mensagem nunca traz detalhes do fornecedor."""


def nvidia_complete(s: AgentSettings) -> Complete:
    if not s.nvidia_api_key:
        raise LLMUnavailable("NVIDIA_API_KEY não configurada")
    from openai import AsyncOpenAI, OpenAIError  # lazy: só com chave configurada

    async def complete(messages: list[dict[str, str]]) -> str:
        try:
            # Um cliente por chamada, fechado no fim: sem ligações penduradas entre pedidos.
            async with AsyncOpenAI(
                base_url=s.nvidia_base_url,
                api_key=s.nvidia_api_key,
                timeout=s.agent_llm_timeout_s,
                max_retries=0,
            ) as client:
                r = await client.chat.completions.create(
                    model=s.nvidia_model, messages=messages, temperature=0.2, max_tokens=600
                )
        except OpenAIError as e:  # sem detalhes: podem incluir cabeçalhos/URL
            raise LLMUnavailable(f"NVIDIA indisponível ({type(e).__name__})") from None
        if not r.choices:
            return ""
        return r.choices[0].message.content or ""

    return complete


def extract_json(text: str) -> dict:
    """Primeiro `{` até ao último `}`; tolera texto à volta. `ValueError` se não for um objeto."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("a resposta não contém JSON")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("a resposta não é um objeto JSON")
    return data
