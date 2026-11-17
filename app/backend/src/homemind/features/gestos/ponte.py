"""Ponte thread de visão -> event loop (#7). Implementa `PublicadorEventos`.

A fila (`asyncio.Queue[Evento]`) e o loop são de P4; P1 chama `publicar` na thread de visão.
Só se regista o tipo do evento: nunca conteúdo, imagens nem dados de pessoas.
"""

import asyncio
import logging
import threading

from homemind.contracts.eventos import Evento

logger = logging.getLogger(__name__)


class PublicadorFila:
    """`publicar` pode ser chamado de qualquer thread; nunca bloqueia, preserva a ordem
    (`call_soon_threadsafe` é FIFO) e não duplica nem repete."""

    def __init__(self, loop: asyncio.AbstractEventLoop, fila: asyncio.Queue[Evento]) -> None:
        self._loop = loop
        self._fila = fila

    def publicar(self, evento: Evento) -> None:
        try:
            self._loop.call_soon_threadsafe(self._por, evento)
        except RuntimeError:
            # Loop fechado no encerramento: contrato permite descartar eventos pendentes.
            logger.debug("evento descartado (loop fechado): %s", evento.tipo)

    def _por(self, evento: Evento) -> None:  # corre no loop
        try:
            self._fila.put_nowait(evento)
        except asyncio.QueueFull:
            logger.warning("evento descartado (fila cheia): %s", evento.tipo)


class PublicadorLista:
    """Guarda os eventos numa lista (afinador e testes). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._eventos: list[Evento] = []

    def publicar(self, evento: Evento) -> None:
        with self._lock:
            self._eventos.append(evento)

    @property
    def eventos(self) -> tuple[Evento, ...]:
        with self._lock:
            return tuple(self._eventos)
