"""NVIDIA (API compatível com OpenAI): texto → proposta de regra. Só configuração, nunca atua.

O modelo só recebe o pedido do utilizador, o schema da regra e as capacidades permitidas:
nunca imagens, eventos, histórico nem tokens. A saída é validada por Pydantic, com uma correção.
"""

import json
from collections.abc import Awaitable, Callable
from typing import get_args

from pydantic import ValidationError

from homemind.contracts.home import Cor
from homemind.contracts.regras import Rule
from homemind.features.engine.config import EngineSettings

Completar = Callable[[list[dict]], Awaitable[str]]


class LLMIndisponivel(Exception):
    pass


class PedidoNaoSuportado(Exception):
    pass


class PropostaInvalida(Exception):
    pass


_SISTEMA = f"""És o configurador do ObjectOS, uma casa controlada por objetos levantados.
Converte o pedido do utilizador numa regra JSON. Responde APENAS com um objeto JSON, sem texto.

Objetos possíveis (campo "objeto"): "caneca", "livro", "comando".
Dispositivos possíveis: "lampada" (ligada, cor, brilho 1-100) e "tomada" (só ligada).
Cores possíveis: {", ".join(get_args(Cor))}.
O "id" é curto, minúsculas sem espaços (ex.: "jantar"). O "nome" começa por "Modo ".

Schema JSON da regra:
{json.dumps(Rule.model_json_schema(), ensure_ascii=False)}

Se o pedido usar outro objeto, outro dispositivo, alarmes/segurança, horários ou for ambíguo,
responde {{"erro": "<explicação curta em português de Portugal>"}}."""


def _extrair_json(texto: str) -> dict:
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fim < inicio:
        raise ValueError("a resposta não contém JSON")
    return json.loads(texto[inicio : fim + 1])


def cliente_nvidia(s: EngineSettings) -> Completar:
    if not s.nvidia_api_key:
        raise LLMIndisponivel("NVIDIA_API_KEY não configurada")
    from openai import AsyncOpenAI, OpenAIError

    async def completar(mensagens: list[dict]) -> str:
        try:
            # Um cliente por chamada, fechado no fim: sem ligações penduradas entre pedidos.
            async with AsyncOpenAI(
                base_url=s.nvidia_base_url, api_key=s.nvidia_api_key, timeout=20, max_retries=0
            ) as client:
                r = await client.chat.completions.create(
                    model=s.nvidia_model, messages=mensagens, temperature=0.2, max_tokens=600
                )
        except OpenAIError as e:  # sem detalhes: podem incluir cabeçalhos/URL
            raise LLMIndisponivel(f"NVIDIA indisponível ({type(e).__name__})") from None
        return r.choices[0].message.content or ""

    return completar


async def propor_regra(texto: str, completar: Completar) -> Rule:
    mensagens = [{"role": "system", "content": _SISTEMA}, {"role": "user", "content": texto}]
    erro = ""
    for _ in range(2):  # resposta inicial + uma correção
        resposta = await completar(mensagens)
        try:
            dados = _extrair_json(resposta)
            if "erro" in dados:
                raise PedidoNaoSuportado(str(dados["erro"])[:200])
            return Rule.model_validate(dados)
        except (ValueError, ValidationError) as e:
            erro = str(e)[:500]
            mensagens += [
                {"role": "assistant", "content": resposta},
                {
                    "role": "user",
                    "content": f"JSON inválido: {erro}. Responde só com o JSON corrigido.",
                },
            ]
    raise PropostaInvalida("O modelo não produziu uma regra válida; reformula o pedido")
