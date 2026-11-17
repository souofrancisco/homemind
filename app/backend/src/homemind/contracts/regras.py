"""Regra (`Rule`): objeto levantado → ações na lâmpada/tomada. Ver docs/contratos.md.

Persistida em `rules.json` pelo motor (P4). `POST /api/rules/parse` só devolve uma proposta; nada
é guardado nem executado antes de `POST /api/rules` com confirmação humana.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from homemind.contracts.home import Cor
from homemind.contracts.visao import ClasseObjeto


class _Entrada(BaseModel):
    """Sem campos extra: um nome errado (ex.: `ativa`) dá 400 em vez de ser ignorado."""

    model_config = ConfigDict(extra="forbid")


class AcaoLampada(_Entrada):
    dispositivo: Literal["lampada"] = "lampada"
    ligada: bool
    cor: Cor | None = None  # None = manter a atual
    brilho: int | None = Field(None, ge=1, le=100)  # para apagar usar ligada=false


class AcaoTomada(_Entrada):
    dispositivo: Literal["tomada"] = "tomada"
    ligada: bool


Acao = Annotated[AcaoLampada | AcaoTomada, Field(discriminator="dispositivo")]


class Rule(_Entrada):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    objeto: ClasseObjeto
    nome: str = Field(min_length=1, max_length=60)
    enabled: bool = True
    acoes: list[Acao] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def _um_por_dispositivo(self) -> "Rule":
        dispositivos = [a.dispositivo for a in self.acoes]
        if len(dispositivos) != len(set(dispositivos)):
            raise ValueError("no máximo uma ação por dispositivo")
        return self
