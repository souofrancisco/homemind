"""Proteções do assistente que não podem perder-se na passagem ao modo tradutor."""

import asyncio
import json
import re

import pytest

from homemind.features.agent.assistant import Assistant
from homemind.features.agent.prompt import build_system_prompt
from homemind.features.agent.tests._fakes import (
    FakeBudget,
    FakeConsumption,
    FakeLLM,
    FakeReceipt,
    ctx,
)
from homemind.features.agent.tests.test_assistant import Appliances, registry
from homemind.features.agent.tools import ToolRegistry

TOOL_BUDGET = json.dumps({"tools": [{"tool": "budget_status", "args": {}}]})


def run(assistant, text="como vai o meu orçamento?", context=None):
    return asyncio.run(assistant.reply(text, context or ctx()))


def test_prompt_diz_o_mes_atual_e_como_resolver_periodos_relativos():
    # Sem a data o LLM escolhia anos errados («outubro» virava 2024).
    system = build_system_prompt(registry().specs(), "2026-11")
    assert "Hoje estamos em 2026-11" in system
    assert "mês passado" in system and "sem ano" in system


def test_prompt_sem_segredos_nem_identificadores():
    system = build_system_prompt(registry().specs(), "2026-11")
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", system)  # nenhum UUID
    assert not re.search(r"nvapi|api[_-]?key|secret|token", system, re.IGNORECASE)


def test_nenhuma_resposta_menciona_telegram():
    textos = [
        run(Assistant(registry(), FakeLLM([TOOL_BUDGET]))).text,
        run(Assistant(registry(), FakeLLM([json.dumps({"tools": []})]))).text,
        run(Assistant(registry(), FakeLLM(["isto não é JSON", "nem isto"]))).text,
        run(Assistant(registry(), None), "olá").text,
        run(Assistant(registry(), None), "porque subiu o meu valor?").text,
    ]
    assert all("telegram" not in t.lower() for t in textos)


def test_llm_a_falhar_avisa_e_responde_pelas_regras():
    r = run(Assistant(registry(), FakeLLM([RuntimeError("rede")])))
    assert r.degraded_reason == "llm_unavailable" and not r.used_llm
    assert r.text.startswith("O assistente está indisponível de momento")
    assert r.tool_result_ids  # os números continuam a vir da ferramenta, por regras


def test_prazo_esgotado_cai_nas_regras_e_avisa():
    lento = FakeLLM([TOOL_BUDGET], delay_s=1.0)
    r = run(Assistant(registry(), lento, timeout_s=0.05, total_timeout_s=0.05))
    assert r.degraded_reason in {"timeout", "llm_unavailable"} and not r.used_llm
    assert "indisponível" in r.text


@pytest.mark.parametrize("papel", ["landlord", "operator"])
def test_senhorio_e_operador_nao_chamam_ferramentas_nem_llm(papel):
    llm = FakeLLM([])  # guião vazio: qualquer chamada rebenta
    consumo = FakeConsumption()
    reg = ToolRegistry(consumo, FakeBudget(), FakeReceipt(), Appliances())
    r = run(Assistant(reg, llm), "quanto gastei?", ctx(papel))
    assert not llm.calls and consumo.calls == 0 and not r.used_llm


def test_pedido_de_acao_nunca_chega_ao_llm():
    llm = FakeLLM([])
    r = run(Assistant(registry(), llm), "desliga a luz da sala")
    assert not llm.calls and not r.used_llm


def test_texto_enorme_e_cortado_antes_de_ir_ao_llm():
    llm = FakeLLM([TOOL_BUDGET])
    run(Assistant(registry(), llm), "x" * 5000)
    assert all(len(m["content"]) <= 4000 for m in llm.calls[0] if m["role"] == "user")
