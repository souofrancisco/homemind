"""`POST /api/households/{id}/agent/messages`: papel × rota, dados simulados, sem rede nem LLM."""

import json
from uuid import UUID

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.agent import AgentResponse
from homemind.features.agent import router as agent_router
from homemind.features.agent.assistant import ACTION_TEXT
from homemind.features.agent.config import AgentSettings
from homemind.features.agent.formatting import format_eur, format_kwh
from homemind.features.agent.tests._fakes import FakeLLM
from homemind.features.agent.tests.conftest import HOUSE_B, as_

URL = f"/api/households/{fx.HOUSEHOLD}/agent/messages"
URL_B = f"/api/households/{HOUSE_B}/agent/messages"
ANA, CARLA, BRUNO = "sub-ana", "sub-carla", "sub-bruno"
LANDLORD, OPERATOR = "sub-senhorio", "sub-operador"
EVA, FRED = "sub-eva", "sub-fred"
CONSUMPTION = "Qual o meu consumo?"


def ask(client, sub, text=CONSUMPTION, url=URL):
    return client.post(url, json={"text": text}, headers=as_(sub))


def err(r):
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return r.status_code, body["error"]["code"]


def ana_values():
    alloc = {a.resident_id: a for a in fx.bill_a()[1]}[fx.ANA]
    return format_kwh(alloc.attributed_total_wh), format_eur(alloc.individual_cents)


# --- caminho feliz, sem LLM --------------------------------------------------------------------


def test_inquilino_sem_llm_recebe_os_numeros_das_fixtures_marcados_simulados(client):
    r = ask(client, ANA)
    assert r.status_code == 200
    body = AgentResponse.model_validate(r.json())  # forma do contrato
    kwh, eur = ana_values()
    assert kwh in body.text and eur in body.text
    assert "simulado" in body.text.lower() and "novembro de 2026" in body.text
    assert body.tool_result_ids and body.proposed_actions == []
    assert body.household_id == fx.HOUSEHOLD


def test_so_ha_numeros_das_fixtures_na_resposta(client):
    text = ask(client, ANA).json()["text"]
    kwh, eur = ana_values()
    stripped = text.replace(kwh, "").replace(eur, "").replace("2026", "")
    assert not any(ch.isdigit() for ch in stripped), stripped


def test_orcamento_so_da_carla(client):
    carla = ask(client, CARLA, "Quanto já gastei do orçamento?").json()["text"]
    spent = next(
        e.data.spent_cents for e in fx.event_samples() if e.type == "alerts.threshold_crossed"
    )
    assert format_eur(spent) in carla and "SIMULADO" in carla
    ana = ask(client, ANA, "Quanto já gastei do orçamento?").json()
    assert "Não tenho dados" in ana["text"] and ana["tool_result_ids"] == []


def test_recibo(client):
    r = ask(client, ANA, "Qual o meu recibo?").json()
    alloc = {a.resident_id: a for a in fx.bill_a()[1]}[fx.ANA]
    assert format_eur(alloc.amount_cents) in r["text"] and r["tool_result_ids"]


def test_resposta_do_llm_fundamentada_passa(client, llm):
    kwh, eur = ana_values()
    llm.complete = FakeLLM(
        [
            json.dumps({"tools": [{"tool": "consumption_summary", "args": {"period": "2026-11"}}]}),
        ]
    )
    r = ask(client, ANA).json()
    assert kwh in r["text"] and eur in r["text"] and "interpretado" not in r["text"]
    assert r["interpreter"] == "llm" and r["tool_result_ids"]


def test_numeros_nao_suportados_dao_resposta_deterministica(client, llm):
    llm.complete = FakeLLM([json.dumps({"tools": [{"tool": "consumption_summary", "args": {}}]})])
    r = ask(client, ANA).json()
    assert "999" not in r["text"] and "SIMULADO" in r["text"]
    assert r["interpreter"] == "llm"


def test_llm_indisponivel_cai_no_recurso(client, llm):
    from homemind.features.agent.llm import LLMUnavailable

    llm.complete = FakeLLM([LLMUnavailable("x")])
    r = ask(client, ANA).json()
    assert r["text"].startswith("O assistente está indisponível") and ana_values()[0] in r["text"]


def test_excecao_inesperada_do_llm_da_200_com_recurso(client, llm, caplog):
    llm.complete = FakeLLM([RuntimeError("Bearer segredo-xyz")])
    with caplog.at_level("WARNING"):
        r = ask(client, ANA)
    assert r.status_code == 200
    assert (
        r.json()["text"].startswith("O assistente está indisponível")
        and ana_values()[0] in r.json()["text"]
    )
    assert "segredo-xyz" not in caplog.text


def test_pedido_de_acao_so_propoe_e_o_llm_nunca_e_chamado(client, llm):
    llm.complete = FakeLLM([])  # esgotado: se fosse chamado, o teste falhava
    r = ask(client, ANA, "Desliga o aquecedor da sala").json()
    assert r["text"] != ACTION_TEXT and "Ainda não foi executado" in r["text"]
    assert r["interpreter"] == "rules"
    assert [a["status"] for a in r["proposed_actions"]] == ["proposed"] and r[
        "tool_result_ids"
    ] == []


def test_pedido_de_acao_sem_dispositivos_e_so_texto(client, llm):
    llm.complete = FakeLLM([])
    r = ask(client, "sub-bruno", "Desliga a luz", url=URL_B).json()
    assert "Não encontro" in r["text"] and r["proposed_actions"] == []


# --- papel × rota e isolamento ------------------------------------------------------------------


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_senhorio_e_operador_403(client, sub):
    assert err(ask(client, sub)) == (403, "forbidden_role")


def test_nao_membro_e_membro_terminado_404(client):
    assert err(ask(client, "sub-desconhecido")) == (404, "household_not_found")
    assert err(ask(client, EVA)) == (404, "household_not_found")  # Eva só está na casa B
    assert err(ask(client, FRED, url=URL_B)) == (404, "household_not_found")  # terminado
    assert client.post(URL, json={"text": "olá"}).status_code == 401


def test_inquilino_de_outra_casa_nao_tem_dados(client):
    r = ask(client, EVA, url=URL_B)
    assert r.status_code == 200
    body = r.json()
    assert "Não tenho dados" in body["text"] and body["tool_result_ids"] == []
    assert "SIMULADO" not in body["text"]
    assert body["household_id"] == str(HOUSE_B)
    # Bruno é inquilino nas duas casas: em B continua sem dados
    assert "Não tenho dados" in ask(client, BRUNO, url=URL_B).json()["text"]


def test_casa_demo_marcada_real_nao_recebe_dados_simulados(client, app):
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET source_kind = 'real' WHERE id = ?", (str(fx.HOUSEHOLD),)
        )
    )
    r = ask(client, ANA).json()
    assert "Não tenho dados" in r["text"] and r["tool_result_ids"] == []


def test_sem_dados_no_periodo(client, now):
    from datetime import UTC, datetime

    now["value"] = datetime(2026, 12, 5, 12, 0, tzinfo=UTC)  # o mês muda, a fatura é de novembro
    r = ask(client, ANA).json()
    assert "Não tenho dados" in r["text"] and "dezembro de 2026" in r["text"]


# --- validação do pedido ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "a" * 2001},
        {},
        {"text": "olá", "resident_id": str(fx.BRUNO)},  # campo extra: o residente vem do token
    ],
)
def test_corpo_invalido_400(client, payload):
    r = client.post(URL, json=payload, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")


def test_texto_no_limite_e_aceite(client):
    assert ask(client, ANA, "a" * 2000).status_code == 200


# --- LLM desligado por omissão -------------------------------------------------------------------


def _settings(monkeypatch, **kw):
    monkeypatch.delenv("AGENT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(agent_router, "get_agent_settings", lambda: AgentSettings(**kw))


def test_get_complete_none_com_chave_mas_llm_desligado(monkeypatch):
    _settings(monkeypatch, nvidia_api_key="chave-de-teste", agent_llm_enabled=False)
    assert agent_router.get_complete() is None


def test_get_complete_none_sem_chave(monkeypatch):
    _settings(monkeypatch, nvidia_api_key="", agent_llm_enabled=True)
    assert agent_router.get_complete() is None


def test_llm_desligado_por_omissao(monkeypatch):
    for name in ("AGENT_LLM_ENABLED", "NVIDIA_API_KEY", "AGENT_TOTAL_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    s = AgentSettings(_env_file=None)
    assert s.agent_llm_enabled is False and s.agent_total_timeout_s == 30.0


def test_scope_demo_nao_chama_llm_em_casa_real(client, llm, monkeypatch, real_house):
    llm.complete = FakeLLM([json.dumps({"tools": []})])
    monkeypatch.setattr(
        agent_router,
        "get_agent_settings",
        lambda: AgentSettings(agent_llm_enabled=True, agent_llm_scope="demo"),
    )
    response = ask(
        client,
        "sub-gina",
        "Quanto gastei este mês?",
        url=f"/api/households/{real_house}/agent/messages",
    )
    assert response.status_code == 200
    assert llm.complete.calls == []
    assert response.json()["interpreter"] == "rules"


def test_get_complete_so_com_flag_e_chave(monkeypatch):
    _settings(monkeypatch, nvidia_api_key="chave-de-teste", agent_llm_enabled=True)
    assert callable(agent_router.get_complete())  # só constrói o cliente; nada é chamado


def test_resposta_tem_id_novo_por_pedido(client):
    a, b = ask(client, ANA).json(), ask(client, ANA).json()
    assert UUID(a["id"]) != UUID(b["id"])
