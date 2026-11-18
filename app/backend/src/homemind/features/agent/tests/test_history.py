"""Histórico da conversa (#111): gravação por troca, isolamento, retenção e nunca ao LLM."""

import json
from datetime import datetime, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.features.agent import history
from homemind.features.agent import router as agent_router
from homemind.features.agent.config import AgentSettings
from homemind.features.agent.tests._fakes import FakeLLM
from homemind.features.agent.tests.conftest import HOUSE_B, as_

HOUSE_A = fx.HOUSEHOLD
ANA, BRUNO, EVA = "sub-ana", "sub-bruno", "sub-eva"
LANDLORD, OPERATOR = "sub-senhorio", "sub-operador"
URL = f"/api/households/{HOUSE_A}/agent/messages"
URL_B = f"/api/households/{HOUSE_B}/agent/messages"


def ask(client, sub, text="Qual o meu consumo?", url=URL):
    r = client.post(url, json={"text": text}, headers=as_(sub))
    assert r.status_code == 200, r.text
    return r.json()


def messages(client, sub, url=URL, **params):
    r = client.get(url, headers=as_(sub), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def err(r):
    body = r.json()
    assert set(body) == {"error"}
    return r.status_code, body["error"]["code"]


def test_grava_a_troca_em_ordem_cronologica(client, now):
    assert messages(client, ANA) == []
    first = ask(client, ANA, "Qual o meu consumo?")
    now["value"] += timedelta(minutes=1)
    second = ask(client, ANA, "E o meu orçamento?")
    got = messages(client, ANA)
    assert [m["role"] for m in got] == ["user", "assistant", "user", "assistant"]
    assert [m["text"] for m in got][::2] == ["Qual o meu consumo?", "E o meu orçamento?"]
    assert got[1]["text"] == first["text"] and got[3]["text"] == second["text"]
    assert {m["household_id"] for m in got} == {str(HOUSE_A)}
    stamps = [datetime.fromisoformat(m["ts"]) for m in got]
    assert stamps == sorted(stamps)
    assert all(set(m) == {"id", "household_id", "role", "text", "ts"} for m in got)


def test_limit_devolve_as_mais_recentes_sem_perder_a_ordem(client, now):
    for i in range(3):
        now["value"] += timedelta(minutes=1)
        ask(client, ANA, f"pergunta {i}")
    got = messages(client, ANA, limit=2)
    assert len(got) == 2 and got[0]["role"] == "user" and got[0]["text"] == "pergunta 2"
    assert got[1]["role"] == "assistant"


def test_pedido_de_acao_tambem_fica_gravado(client):
    r = ask(client, ANA, "Desliga o aquecedor da sala")
    assert r["proposed_actions"]
    got = messages(client, ANA)
    assert [m["role"] for m in got] == ["user", "assistant"]
    assert got[0]["text"] == "Desliga o aquecedor da sala" and got[1]["text"] == r["text"]


def test_isolamento_entre_residentes_da_mesma_casa(client):
    ask(client, ANA, "pergunta da Ana")
    ask(client, BRUNO, "pergunta do Bruno")
    assert {m["text"] for m in messages(client, ANA) if m["role"] == "user"} == {"pergunta da Ana"}
    assert {m["text"] for m in messages(client, BRUNO) if m["role"] == "user"} == {
        "pergunta do Bruno"
    }


def test_isolamento_entre_casas_do_mesmo_residente(client):
    ask(client, BRUNO, "na casa A")  # Bruno é inquilino nas casas A e B
    ask(client, BRUNO, "na casa B", url=URL_B)
    a = [m for m in messages(client, BRUNO) if m["role"] == "user"]
    b = [m for m in messages(client, BRUNO, url=URL_B) if m["role"] == "user"]
    assert [m["text"] for m in a] == ["na casa A"] and a[0]["household_id"] == str(HOUSE_A)
    assert [m["text"] for m in b] == ["na casa B"] and b[0]["household_id"] == str(HOUSE_B)
    assert messages(client, EVA, url=URL_B) == []


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_senhorio_e_operador_403(client, sub):
    ask(client, ANA, "privado")
    assert err(client.get(URL, headers=as_(sub))) == (403, "forbidden_role")


def test_nao_membro_404_e_sem_token_401(client):
    assert err(client.get(URL, headers=as_("sub-desconhecido"))) == (404, "household_not_found")
    assert err(client.get(URL, headers=as_(EVA))) == (404, "household_not_found")
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc"])
def test_limit_fora_de_1_a_100_da_400(client, limit):
    assert err(client.get(URL, headers=as_(ANA), params={"limit": limit})) == (
        400,
        "invalid_request",
    )


def test_limit_100_e_aceite(client):
    assert client.get(URL, headers=as_(ANA), params={"limit": 100}).status_code == 200


def test_retencao_por_numero(client, now, monkeypatch):
    monkeypatch.setattr(
        agent_router, "get_agent_settings", lambda: AgentSettings(agent_history_keep=4)
    )
    for i in range(3):
        now["value"] += timedelta(minutes=1)
        ask(client, ANA, f"pergunta {i}")
    ask(client, BRUNO, "do Bruno")  # o corte de uma não toca nas do outro
    got = messages(client, ANA)
    assert [m["text"] for m in got if m["role"] == "user"] == ["pergunta 1", "pergunta 2"]
    assert len(got) == 4 and len(messages(client, BRUNO)) == 2


def test_retencao_por_dias(client, now, monkeypatch):
    monkeypatch.setattr(
        agent_router, "get_agent_settings", lambda: AgentSettings(agent_history_days=30)
    )
    ask(client, ANA, "antiga")
    now["value"] += timedelta(days=29)
    ask(client, ANA, "a meio")
    assert [m["text"] for m in messages(client, ANA) if m["role"] == "user"] == ["antiga", "a meio"]
    now["value"] += timedelta(days=2)  # a «antiga» passa a ter 31 dias
    ask(client, ANA, "recente")
    assert [m["text"] for m in messages(client, ANA) if m["role"] == "user"] == [
        "a meio",
        "recente",
    ]


def test_record_exchange_corta_sem_tocar_nos_outros(app, now):
    def run(conn):
        for i in range(5):
            history.record_exchange(
                conn,
                fx.HOUSEHOLD,
                fx.ANA,
                f"u{i}",
                f"r{i}",
                now["value"] + timedelta(minutes=i),
                6,
                30,
            )
        history.record_exchange(conn, fx.HOUSEHOLD, fx.BRUNO, "b", "rb", now["value"], 6, 30)
        return (
            [m.text for m in history.list_messages(conn, fx.HOUSEHOLD, fx.ANA, 100)],
            [m.text for m in history.list_messages(conn, fx.HOUSEHOLD, fx.BRUNO, 100)],
        )

    ana, bruno = app.state.db.run_sync(run)
    assert ana == ["u2", "r2", "u3", "r3", "u4", "r4"] and bruno == ["b", "rb"]


def test_o_llm_nunca_recebe_mensagens_anteriores(client, llm):
    llm.complete = FakeLLM(
        [
            json.dumps({"answer": "Sem números."}),
            json.dumps({"answer": "Sem números."}),
        ]
    )
    ask(client, ANA, "primeira pergunta secreta")
    ask(client, ANA, "segunda pergunta")
    assert len(messages(client, ANA)) == 4
    second_call = json.dumps(llm.complete.calls[1])
    assert "segunda pergunta" in second_call
    assert "primeira pergunta secreta" not in second_call
    assert "Sem números" not in second_call  # nem a resposta anterior
