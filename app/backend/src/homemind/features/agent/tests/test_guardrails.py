from decimal import Decimal

import pytest

from homemind.features.agent.guardrails import extract_numbers, invented_numbers, is_action_request


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("gastaste 1 234,56 € este mês", [Decimal("1234.56")]),
        ("gastaste 1 234,56 €", [Decimal("1234.56")]),
        ("gastaste 1 234,56 €", [Decimal("1234.56")]),
        ("20,00 € e 80 %", [Decimal("20.00"), Decimal("80")]),
        ("cerca de 12.5 kWh.", [Decimal("12.5")]),
        ("1.234,56 €", [Decimal("1234.56")]),
        ("sem números", []),
        ("valor12 e abc", []),
    ],
)
def test_extract_numbers(text, expected):
    assert [v for _, v in extract_numbers(text)] == expected


def test_invented_numbers():
    allowed = frozenset({Decimal("20.00"), Decimal("2026")})
    assert invented_numbers("20 € em novembro de 2026", allowed) == []
    assert invented_numbers("20,00 € mas também 35 € e 80 %", allowed) == ["35", "80"]


def test_numero_da_pergunta_nao_e_permitido():
    pergunta = "gastei 50 € ou mais?"
    allowed = frozenset(v for _, v in extract_numbers("20,00 €"))  # os da pergunta ficam de fora
    assert invented_numbers(f"Sim, {pergunta}", allowed) == ["50"]


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
