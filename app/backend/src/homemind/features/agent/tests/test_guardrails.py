import pytest

from homemind.features.agent.guardrails import is_action_request


@pytest.mark.parametrize(
    "text",
    [
        "Desliga o aquecedor às 23h",
        "podes ligar a luz?",
        "arma o alarme",
        "ativa o cenário de noite",
        "problema de segurança",
    ],
)
def test_pedidos_de_acao(text):
    assert is_action_request(text)


@pytest.mark.parametrize(
    "text", ["quanto gastei este mês?", "o aquecedor está ligado?", "mostra o meu recibo"]
)
def test_perguntas_nao_sao_acoes(text):
    assert not is_action_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "A tomada está desligada?",
        "Quanto gastou a tomada enquanto esteve desligada?",
        "Quanto consome a luz apagada?",
        "O que posso mudar para gastar menos?",
        "Põe-me o consumo de novembro",
        "Qual a cor da luz?",
        "Qual a cor da fatura?",
        "A luz está acesa?",
        "Como desligo a luz?",
        "a tomada ficou desligada ontem",
        "mostra o brilho médio da semana",
    ],
)
def test_leitura_com_palavras_de_acao_nao_e_pedido_de_acao(text):
    assert not is_action_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "desligue a luz",
        "apague a luz",
        "acenda a luz",
        "ligue a luz",
        "põe a luz azul",
        "muda a luz para vermelho",
        "desliga a tomada",
        "podes desligar a lâmpada?",
        "põe o brilho a 50",
        "brilho da luz a 100%",
        "não desligues a tomada",
    ],
)
def test_imperativo_e_infinitivo_sao_pedidos_de_acao(text):
    assert is_action_request(text)
