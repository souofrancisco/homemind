"""O que o backend (Pessoa 4) expõe ao frontend (Pessoa 5): `GET /status` e mensagens de `WS /ws`.

Só texto e números; nunca imagens.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from homemind.contracts.base import Contrato
from homemind.contracts.home import EstadoCasa

EstadoMaquina = Literal["inativo", "ativo", "em_espera", "suspenso"]


class Status(Contrato):
    """Resposta de `GET /status`."""

    camara_ok: bool
    mcp_ok: bool
    home_backend: Literal["fake", "mcp"]  # fake = SIMULADO


class LinhaRegisto(Contrato):
    """Uma linha do registo em PT-PT; também o formato de cada linha de `events.jsonl`."""

    hora: datetime
    texto: str


class MensagemEstado(Contrato):
    """Fotografia completa do sistema; enviada ao ligar o WS e a cada mudança."""

    tipo: Literal["estado"] = "estado"
    estado: EstadoMaquina
    modo: str | None  # id da regra ativa (ou guardada, se suspenso); None se nenhuma
    modo_nome: str | None
    ha_alguem: bool
    segundos_para_suspender: float | None  # só em «em_espera»
    status: Status
    casa: EstadoCasa
    poupanca_wh: float = Field(ge=0)
    poupanca_eur: float = Field(ge=0)


class MensagemRegisto(Contrato):
    tipo: Literal["registo"] = "registo"
    linha: LinhaRegisto


MensagemWS = Annotated[MensagemEstado | MensagemRegisto, Field(discriminator="tipo")]

mensagem_ws_adapter: TypeAdapter[MensagemEstado | MensagemRegisto] = TypeAdapter(MensagemWS)
