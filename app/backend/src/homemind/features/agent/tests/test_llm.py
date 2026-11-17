import asyncio
import sys
import types

import pytest

from homemind.features.agent.config import AgentSettings
from homemind.features.agent.llm import LLMUnavailable, extract_json, nvidia_complete


def test_sem_chave_levanta_sem_rede(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    boom = types.ModuleType("openai")  # se fosse importado, falhava o teste
    monkeypatch.setitem(sys.modules, "openai", boom)
    with pytest.raises(LLMUnavailable):
        nvidia_complete(AgentSettings(nvidia_api_key=""))


def test_defaults_iguais_ao_motor(monkeypatch):
    for name in ("NVIDIA_BASE_URL", "NVIDIA_MODEL", "AGENT_LLM_TIMEOUT_S", "AGENT_MAX_STEPS"):
        monkeypatch.delenv(name, raising=False)
    s = AgentSettings(nvidia_api_key="")
    assert s.nvidia_base_url == "https://integrate.api.nvidia.com/v1"
    assert s.nvidia_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert s.agent_llm_timeout_s == 20.0 and s.agent_max_steps == 4


def _stub_openai(monkeypatch, *, error=None, content="olá"):
    class OpenAIError(Exception):
        pass

    seen = {}

    class Completions:
        async def create(self, **kw):
            seen["create"] = kw
            if error:
                raise OpenAIError(error)
            msg = types.SimpleNamespace(content=content)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class AsyncOpenAI:
        def __init__(self, **kw):
            seen["client"] = kw
            self.chat = types.SimpleNamespace(completions=Completions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    mod = types.ModuleType("openai")
    mod.AsyncOpenAI, mod.OpenAIError = AsyncOpenAI, OpenAIError
    monkeypatch.setitem(sys.modules, "openai", mod)
    return seen


def test_cliente_com_openai_falso(monkeypatch):
    seen = _stub_openai(monkeypatch)
    complete = nvidia_complete(AgentSettings(nvidia_api_key="k", agent_llm_timeout_s=5))
    assert asyncio.run(complete([{"role": "user", "content": "x"}])) == "olá"
    assert seen["client"]["timeout"] == 5 and seen["client"]["max_retries"] == 0


def test_erro_do_fornecedor_so_com_o_tipo(monkeypatch):
    _stub_openai(monkeypatch, error="Bearer segredo https://x")
    complete = nvidia_complete(AgentSettings(nvidia_api_key="k"))
    with pytest.raises(LLMUnavailable) as e:
        asyncio.run(complete([]))
    assert "segredo" not in str(e.value) and "OpenAIError" in str(e.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('Aqui está:\n```json\n{"answer": "olá"}\n```', {"answer": "olá"}),
        ('{"tool": "x", "args": {"p": {"q": 1}}} fim', {"tool": "x", "args": {"p": {"q": 1}}}),
    ],
)
def test_extract_json(text, expected):
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "sem json", "} {", "{inválido}", "{'a': 1}", "{"])
def test_extract_json_invalido(text):
    with pytest.raises(ValueError):
        extract_json(text)
