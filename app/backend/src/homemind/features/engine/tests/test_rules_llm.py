"""Rules (validação/persistência) e texto→regra com um LLM falso (sem NVIDIA)."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from homemind.contracts.regras import AcaoLampada, AcaoTomada, Rule
from homemind.features.engine.llm import PedidoNaoSuportado, PropostaInvalida, propor_regra
from homemind.features.engine.rules import RulesStore, descrever


def test_predefinidas_criadas_e_persistidas(tmp_path):
    s = RulesStore(tmp_path / "rules.json")
    s.carregar()
    assert {r.objeto for r in s.listar()} == {"caneca", "livro", "comando"}
    s2 = RulesStore(tmp_path / "rules.json")
    s2.carregar()
    assert s2.listar() == s.listar()


def test_regra_ativa_desativa_outras_do_mesmo_objeto(tmp_path):
    s = RulesStore(tmp_path / "rules.json")
    s.carregar()
    nova = Rule(
        id="jantar",
        nome="Modo jantar",
        objeto="livro",
        acoes=[AcaoTomada(ligada=False)],
    )
    s.guardar(nova)
    assert s.ativa_para("livro").id == "jantar"
    assert not s.obter("leitura").enabled


def test_regras_invalidas_rejeitadas():
    with pytest.raises(ValidationError):
        AcaoTomada(ligada=True, cor="azul")
    with pytest.raises(ValidationError):
        Rule(id="x", nome="X", objeto="chaves", acoes=[AcaoTomada(ligada=True)])
    with pytest.raises(ValidationError):
        Rule(id="x", nome="X", objeto="livro", acoes=[])
    with pytest.raises(ValidationError):
        AcaoLampada(ligada=True, brilho=150)


def test_descricao_pt():
    r = Rule(
        id="x",
        nome="Modo x",
        objeto="caneca",
        acoes=[AcaoLampada(ligada=True, cor="verde", brilho=50)],
    )
    assert descrever(r) == "Ao levantar a caneca, ativa «Modo x»: liga a luz verde a 50%."


def _llm(*respostas):
    pedidos = []

    async def completar(mensagens):
        pedidos.append(mensagens)
        return respostas[len(pedidos) - 1]

    return completar, pedidos


VALIDA = {
    "id": "verde",
    "nome": "Modo verde",
    "objeto": "livro",
    "acoes": [{"dispositivo": "lampada", "ligada": True, "cor": "verde"}],
}


def test_llm_resposta_valida():
    completar, _ = _llm("Aqui está:\n" + json.dumps(VALIDA))
    assert asyncio.run(propor_regra("luz verde com o livro", completar)).id == "verde"


def test_llm_uma_correcao():
    completar, pedidos = _llm('{"id": "verde"}', json.dumps(VALIDA))
    assert asyncio.run(propor_regra("luz verde com o livro", completar)).objeto == "livro"
    assert len(pedidos) == 2 and "JSON inválido" in pedidos[1][-1]["content"]


def test_llm_invalido_duas_vezes():
    completar, _ = _llm("nada", "{}")
    with pytest.raises(PropostaInvalida):
        asyncio.run(propor_regra("faz qualquer coisa", completar))


def test_llm_recusa_pedido_nao_suportado():
    completar, _ = _llm('{"erro": "Não controlo o alarme"}')
    with pytest.raises(PedidoNaoSuportado):
        asyncio.run(propor_regra("arma o alarme com o comando", completar))


def test_prompt_sem_segredos(monkeypatch):
    completar, pedidos = _llm(json.dumps(VALIDA))
    asyncio.run(propor_regra("livro verde", completar))
    texto = json.dumps(pedidos[0])
    assert "api_key" not in texto.lower() and "token" not in texto.lower()


def test_campo_desconhecido_rejeitado():
    with pytest.raises(ValidationError):  # ex.: nome antigo `ativa` em vez de `enabled`
        Rule.model_validate(
            {
                "id": "x",
                "nome": "X",
                "objeto": "livro",
                "ativa": True,
                "acoes": [{"dispositivo": "tomada", "ligada": True}],
            }
        )
