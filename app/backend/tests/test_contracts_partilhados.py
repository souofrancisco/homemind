import asyncio
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from homemind.contracts.home import EstadoCasa, EstadoLampada, EstadoTomada, Home
from homemind.contracts.painel import (
    LinhaRegisto,
    MensagemEstado,
    MensagemRegisto,
    Status,
    mensagem_ws_adapter,
)
from homemind.contracts.regras import AcaoLampada, AcaoTomada, PropostaRegra, Regra

HORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

REGRA_DO_PLANO = (
    '{"id":"leitura","objeto":"livro","nome":"Modo leitura","acoes":['
    '{"dispositivo":"lampada","ligada":true,"cor":"branco_quente","brilho":40},'
    '{"dispositivo":"tomada","ligada":true}]}'
)

CASA = EstadoCasa(
    lampada=EstadoLampada(ligada=True, cor="branco_quente", brilho=40),
    tomada=EstadoTomada(ligada=True),
    consumo_w=12.5,
    simulado=True,
)


def test_regra_do_plano_valida_e_distingue_acoes():
    regra = Regra.model_validate_json(REGRA_DO_PLANO)
    assert regra.ativa is True
    assert isinstance(regra.acoes[0], AcaoLampada) and regra.acoes[0].brilho == 40
    assert isinstance(regra.acoes[1], AcaoTomada)
    assert Regra.model_validate_json(regra.model_dump_json()) == regra


@pytest.mark.parametrize(
    "alteracao",
    [
        {"objeto": "chaves"},
        {"acoes": []},
        {"acoes": [{"dispositivo": "alarme", "ligada": False}]},
        {"acoes": [{"dispositivo": "lampada", "ligada": True, "brilho": 101}]},
        {"id": "Modo Leitura"},
    ],
)
def test_regra_invalida_rejeitada(alteracao):
    with pytest.raises(ValidationError):
        Regra.model_validate({**json.loads(REGRA_DO_PLANO), **alteracao})


def test_proposta_de_regra_ida_e_volta():
    proposta = PropostaRegra(
        regra=Regra.model_validate_json(REGRA_DO_PLANO), descricao="Acende a luz a 40%."
    )
    assert PropostaRegra.model_validate_json(proposta.model_dump_json()) == proposta


def test_mensagens_ws_ida_e_volta_pelo_discriminador():
    estado = MensagemEstado(
        estado="em_espera",
        modo="leitura",
        modo_nome="Modo leitura",
        ha_alguem=False,
        segundos_para_suspender=7.5,
        status=Status(camara_ok=True, mcp_ok=False, home_backend="fake"),
        casa=CASA,
        poupanca_wh=1.2,
        poupanca_eur=0.0003,
    )
    registo = MensagemRegisto(linha=LinhaRegisto(hora=HORA, texto="Livro levantado."))
    for mensagem in (estado, registo):
        assert mensagem_ws_adapter.validate_json(mensagem.model_dump_json()) == mensagem


def test_estado_da_maquina_desconhecido_rejeitado():
    with pytest.raises(ValidationError):
        mensagem_ws_adapter.validate_python({"tipo": "estado", "estado": "a_dormir"})


class _HomeMinima:
    """Implementação mínima só para provar que o Protocol é implementável sem hardware."""

    def __init__(self) -> None:
        self._casa = CASA

    async def definir_lampada(self, ligada: bool, cor: str | None, brilho: int | None) -> bool:
        anterior = self._casa.lampada
        lampada = EstadoLampada(
            ligada=ligada,
            cor=anterior.cor if cor is None else cor,
            brilho=anterior.brilho if brilho is None else brilho,
        )
        self._casa = self._casa.model_copy(update={"lampada": lampada})
        return True

    async def definir_tomada(self, ligada: bool) -> bool:
        self._casa = self._casa.model_copy(update={"tomada": EstadoTomada(ligada=ligada)})
        return True

    async def ler_consumo(self) -> float:
        return self._casa.consumo_w or 0.0

    async def estado(self) -> EstadoCasa:
        return self._casa


def test_protocolo_home_implementavel_sem_hardware():
    async def cenario(home: Home) -> EstadoCasa:
        assert await home.definir_lampada(True, None, 20)
        assert await home.definir_tomada(False)
        return await home.estado()

    casa = asyncio.run(cenario(_HomeMinima()))
    assert casa.lampada.brilho == 20 and casa.lampada.cor == "branco_quente"
    assert casa.tomada.ligada is False and casa.simulado is True
