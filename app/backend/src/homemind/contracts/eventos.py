"""Eventos que gestos/presença (Pessoa 2) publicam na `asyncio.Queue` do motor (Pessoa 4).

Assinaturas de `docs/objectos-plano.md` §3. Só texto: nunca imagens nem dados de pessoas.
"""

from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from homemind.contracts.visao import ClasseObjeto, FrameDeteccoes


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


class ProcessadorEventos(Protocol):
    """Gestos + presença (P2). Com estado, síncrono, sem I/O: recebe frames por ordem crescente
    de `indice` e devolve os eventos que esse frame confirma (`()` na maioria). `hora` dos
    eventos = `frame.hora`. Usado pela thread de visão (P1) e pelo afinador offline."""

    def processar(self, frame: FrameDeteccoes) -> tuple[Evento, ...]: ...


class PublicadorEventos(Protocol):
    """Ponte thread de visão -> event loop (P2 implementa; P4 consome a `asyncio.Queue[Evento]`).

    `publicar` pode ser chamado de qualquer thread, nunca bloqueia, preserva a ordem e não
    duplica. A implementação real faz `loop.call_soon_threadsafe(fila.put_nowait, evento)`."""

    def publicar(self, evento: Evento) -> None: ...
