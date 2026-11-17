"""Thread de visão (#28): FonteVideo → Detetor (P1) → ProcessadorObjectOS (P2) → Publicador → motor.

Só frames novos (`indice` mudou); sem câmara não há frames novos, logo não há eventos. Nunca guarda
nem regista imagens: só passam metadados (`FrameDeteccoes`) e eventos.
"""

import importlib
import logging
import threading
import time

from homemind.contracts.eventos import ProcessadorEventos, PublicadorEventos
from homemind.contracts.video import FonteVideo
from homemind.contracts.visao import Detetor, FrameDeteccoes

log = logging.getLogger(__name__)


class DetetorIndisponivel(Exception):
    pass


def carregar_detetor(especificacao: str) -> Detetor:
    """`modulo:Classe` → instância sem argumentos com `detetar` (mesma convenção do afinador)."""
    modulo, sep, nome = especificacao.partition(":")
    if not sep or not modulo or not nome:
        raise DetetorIndisponivel(f"VISAO_DETETOR inválido ({especificacao!r}); usar modulo:Classe")
    try:
        detetor = getattr(importlib.import_module(modulo), nome)()
    except (ImportError, AttributeError) as e:
        raise DetetorIndisponivel(f"{especificacao}: {type(e).__name__}") from e
    if not callable(getattr(detetor, "detetar", None)):
        raise DetetorIndisponivel(f"{especificacao} não tem detetar(FrameVideo)")
    return detetor


class ThreadVisao:
    def __init__(
        self,
        fonte: FonteVideo,
        detetor: Detetor,
        processador: ProcessadorEventos,
        publicador: PublicadorEventos,
        espera_s: float = 0.005,
    ) -> None:
        self.fonte = fonte
        self.detetor = detetor
        self.processador = processador
        self.publicador = publicador
        self.espera_s = espera_s
        self.frames = 0  # frames processados (diagnóstico)
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._ultima: tuple[FrameDeteccoes, float] | None = None
        self._ultima_lock = threading.Lock()

    def ultima_deteccao(self, idade_max_s: float = 1.0) -> FrameDeteccoes | None:
        """Últimas deteções (só metadados), ou None se mais antigas que `idade_max_s`."""
        with self._ultima_lock:
            if self._ultima is None:
                return None
            det, quando = self._ultima
        return det if time.monotonic() - quando <= idade_max_s else None

    def iniciar(self) -> None:
        self._parar.clear()
        self._thread = threading.Thread(target=self._ciclo, name="visao", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _ciclo(self) -> None:
        ultimo: int | None = None
        while not self._parar.is_set():
            frame = self.fonte.ultimo_frame()
            if frame is None or frame.indice == ultimo:
                time.sleep(self.espera_s)
                continue
            ultimo = frame.indice
            try:
                det = self.detetor.detetar(frame)
                with self._ultima_lock:
                    self._ultima = (det, time.monotonic())
                eventos = self.processador.processar(det)
            except Exception:  # um frame mau não pára a visão; sem detalhes do frame no log
                log.exception("falha a processar frame")
                continue
            self.frames += 1
            for evento in eventos:
                self.publicador.publicar(evento)
