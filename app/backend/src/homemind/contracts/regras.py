"""Regra objeto -> ações (Pessoa 4), persistida em `rules.json` e editada pela UI (Pessoa 5).

Formato JSON do plano §3. `POST /rules/parse` só devolve uma proposta; nada é guardado nem
executado antes de `POST /rules` com confirmação humana.
"""

from typing import Annotated, Literal

from pydantic import Field

from homemind.contracts.base import Contrato
from homemind.contracts.home import BRILHO_MAX, BRILHO_MIN
from homemind.contracts.visao import ClasseObjeto


class AcaoLampada(Contrato):
    dispositivo: Literal["lampada"] = "lampada"
    ligada: bool
    cor: str | None = None
    brilho: int | None = Field(default=None, ge=BRILHO_MIN, le=BRILHO_MAX)


class AcaoTomada(Contrato):
    dispositivo: Literal["tomada"] = "tomada"
    ligada: bool


Acao = Annotated[AcaoLampada | AcaoTomada, Field(discriminator="dispositivo")]


class Regra(Contrato):
    id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=40)
    objeto: ClasseObjeto
    nome: str = Field(min_length=1, max_length=60)
    acoes: tuple[Acao, ...] = Field(min_length=1)
    ativa: bool = True


class PedidoRegra(Contrato):
    """Corpo de `POST /rules/parse`."""

    texto: str = Field(min_length=1, max_length=500)


class PropostaRegra(Contrato):
    """Resposta de `POST /rules/parse`: pré-visualização, ainda não persistida."""

    regra: Regra
    descricao: str  # explicação em PT-PT do que a regra fará
