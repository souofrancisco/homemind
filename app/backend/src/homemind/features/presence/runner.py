"""Thread da porta (PRES-02): FonteVideo -> máscara -> detetor de pessoas -> contador -> evento.

Só frames novos. O frame é recortado à soleira antes do detetor e nunca é guardado,
registado nem enviado: sai apenas `presence.door_crossed` (sentido e confiança). Sem câmara não há
frames novos, logo não há eventos; e nunca se infere «casa vazia» daqui.
"""

import importlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.domain_events import PresenceDoorCrossed
from homemind.contracts.presence import DoorCrossed
from homemind.contracts.video import FonteVideo, FrameVideo
from homemind.features.presence.door import (
    ContadorPorta,
    DetetorPessoas,
    Passagem,
    Soleira,
    recortar,
)

log = logging.getLogger(__name__)


def carregar_detetor_pessoas(especificacao: str) -> DetetorPessoas:
    """`modulo:Classe` -> instância sem argumentos com `detetar(imagem)`."""
    modulo, sep, nome = especificacao.partition(":")
    if not sep or not modulo or not nome:
        raise ValueError("PRESENCE_DETETOR inválido; usar modulo:Classe")
    try:
        detetor = getattr(importlib.import_module(modulo), nome)()
    except (ImportError, AttributeError) as e:
        raise ValueError(f"PRESENCE_DETETOR indisponível ({type(e).__name__})") from e
    if not callable(getattr(detetor, "detetar", None)):
        raise ValueError("PRESENCE_DETETOR sem detetar(imagem)")
    return detetor


def evento_de_passagem(
    household_id: UUID, passagem: Passagem, ts: datetime, origin: Origin
) -> PresenceDoorCrossed:
    prov = Provenance(origin=origin, kind=ValueKind.inferred)
    return PresenceDoorCrossed(
        ts=ts,
        household_id=household_id,
        provenance=prov,
        data=DoorCrossed(
            ts=ts, direction=passagem.direcao, confidence=passagem.confianca, provenance=prov
        ),
    )


class ProcessadorPorta:
    """Um frame de cada vez; síncrono, para a thread e para testes."""

    def __init__(
        self,
        soleira: Soleira,
        detetor: DetetorPessoas,
        contador: ContadorPorta,
        publicar: Callable[[PresenceDoorCrossed], object],
        household_id: UUID,
        origin: Origin,
        *,
        relogio: Callable[[], float] = time.monotonic,
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.soleira, self.detetor, self.contador = soleira, detetor, contador
        self._publicar, self._casa, self._origin = publicar, household_id, origin
        self._relogio, self._agora = relogio, agora

    def processar(self, frame: FrameVideo) -> list[PresenceDoorCrossed]:
        altura, largura = frame.imagem.shape[:2]
        recorte, (x0, y0) = recortar(frame.imagem, self.soleira.roi)
        # O detetor só vê a soleira; as caixas voltam às coordenadas do frame inteiro.
        pessoas = [
            replace(p, x1=p.x1 + x0, x2=p.x2 + x0, y1=p.y1 + y0, y2=p.y2 + y0)
            for p in self.detetor.detetar(recorte)
        ]
        passagens = self.contador.atualizar(frame.t, pessoas, largura, altura)
        agora, t_agora = self._agora(), self._relogio()
        eventos = [
            evento_de_passagem(
                self._casa, p, agora - timedelta(seconds=max(0.0, t_agora - p.t)), self._origin
            )
            for p in passagens
        ]
        for e in eventos:
            self._publicar(e)
        return eventos


class ThreadPorta:
    def __init__(self, fonte: FonteVideo, processador: ProcessadorPorta, espera_s: float = 0.005):
        self.fonte, self.processador, self.espera_s = fonte, processador, espera_s
        self.frames = 0
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    def iniciar(self) -> None:
        self._parar.clear()
        self._thread = threading.Thread(target=self._ciclo, name="porta", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _ciclo(self) -> None:
        preparar = getattr(self.processador.detetor, "preparar", None)
        if preparar is not None:
            try:
                preparar()
            except Exception as e:  # pesos/dependências em falta: só a porta desliga
                log.error("deteção da porta indisponível (%s)", type(e).__name__)
                return
        ultimo: int | None = None
        while not self._parar.is_set():
            frame = self.fonte.ultimo_frame()
            if frame is None or frame.indice == ultimo:
                time.sleep(self.espera_s)
                continue
            ultimo = frame.indice
            try:
                self.processador.processar(frame)
            except Exception as e:  # um frame mau não pára a porta; nunca o conteúdo
                log.warning("falha a processar frame da porta (%s)", type(e).__name__)
                continue
            self.frames += 1
