"""Eventos tipados consumidos pela ponte thread → event loop mantida em `gestos.ponte`."""

from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from homemind.contracts.visao import ClasseObjeto


class ObjetoLevantado(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal["objeto_levantado"] = "objeto_levantado"
    classe: ClasseObjeto
    hora: datetime


class Presenca(BaseModel):
    """Só transições: emitido quando `ha_alguem` muda."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal["presenca"] = "presenca"
    ha_alguem: bool
    hora: datetime


Evento = Annotated[ObjetoLevantado | Presenca, Field(discriminator="tipo")]

# Para ler eventos de JSON (WS, events.jsonl): `evento_adapter.validate_json(linha)`.
evento_adapter: TypeAdapter[ObjetoLevantado | Presenca] = TypeAdapter(Evento)


class PublicadorEventos(Protocol):
    """Publica um evento tipado a partir de qualquer thread sem o expor em logs."""

    def publicar(self, evento: Evento) -> None: ...
