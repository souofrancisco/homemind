"""Fontes de vídeo (câmara RTSP e clip de reserva) que mantêm só o frame mais recente.

Os frames vivem em memória e são substituídos; nada é gravado, enfileirado ou registado.
O URL da fonte pode conter credenciais: nunca o escrever em logs ou erros.
"""

import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, Protocol

import cv2

from homemind.contracts.video import FrameVideo
from homemind.core.config import Settings

log = logging.getLogger(__name__)

FPS_CLIP_OMISSAO = 25.0


class Captura(Protocol):
    def read(self) -> tuple[bool, Any]: ...

    def get(self, propriedade: int) -> float: ...

    def release(self) -> None: ...


def abrir_rtsp(fonte: str, *, timeout_abrir_ms: int, timeout_ler_ms: int) -> Captura:
    """RTSP sobre TCP. Os timeouts fazem `read()` falhar em vez de ficar preso sem rede."""
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    captura = cv2.VideoCapture(
        fonte,
        cv2.CAP_FFMPEG,
        [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            timeout_abrir_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            timeout_ler_ms,
        ],
    )
    captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return captura


def abrir_clip(caminho: str) -> Captura:
    return cv2.VideoCapture(caminho, cv2.CAP_FFMPEG)


class _FonteThread:
    """Thread que lê uma captura e guarda o último frame; reabre com backoff quando falha.

    Implementa `homemind.contracts.video.FonteVideo`.
    """

    ao_vivo = True

    def __init__(
        self,
        fonte: str,
        *,
        abrir: Callable[[str], Captura],
        sem_frame_s: float = 3.0,
        reconexao_s: Sequence[float] = (1, 2, 4, 8, 10),
        relogio: Callable[[], float] = time.monotonic,
        esperar: Callable[[float], object] | None = None,
        pausa_falha_s: float = 0.05,
    ) -> None:
        self._fonte = fonte
        self._abrir = abrir
        self._sem_frame_s = sem_frame_s
        self._reconexao_s = tuple(reconexao_s)
        self._relogio = relogio
        self._pausa_falha_s = pausa_falha_s
        self._lock = threading.Lock()
        self._frame: FrameVideo | None = None
        self._indice = 0
        self._reconexoes = 0
        self._parar = threading.Event()
        # Esperar no evento de paragem: parar() interrompe logo qualquer espera.
        self._esperar = esperar or self._parar.wait
        self._thread: threading.Thread | None = None

    def iniciar(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._ciclo, name="fonte-video", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)  # um read() preso não bloqueia o encerramento
            self._thread = None

    def ultimo_frame(self) -> FrameVideo | None:
        with self._lock:
            return self._frame

    @property
    def camara_ok(self) -> bool:
        frame = self.ultimo_frame()
        return frame is not None and self._relogio() - frame.t < self._sem_frame_s

    @property
    def reconexoes(self) -> int:
        """Quantas vezes a fonte teve de ser reaberta depois de uma falha."""
        return self._reconexoes

    def _ciclo(self) -> None:
        tentativa = 0
        while not self._parar.is_set():
            reabrir_ja, leu_frames = self._sessao()
            if self._parar.is_set():
                break
            if leu_frames:
                tentativa = 0
            if reabrir_ja:
                continue
            espera = self._reconexao_s[min(tentativa, len(self._reconexao_s) - 1)]
            tentativa += 1
            self._reconexoes += 1
            self._esperar(espera)

    def _sessao(self) -> tuple[bool, bool]:
        """Abre a fonte (aqui, não em iniciar(): ligar pode demorar) e lê até falhar.

        Devolve (reabrir já sem backoff, leu pelo menos um frame).
        """
        lidos = 0
        captura: Captura | None = None
        try:
            captura = self._abrir(self._fonte)
            self._ao_abrir(captura)
            ultimo_ok = self._relogio()
            while not self._parar.is_set():
                ok, imagem = captura.read()
                if ok:
                    lidos += 1
                    with self._lock:
                        self._indice += 1
                        self._frame = FrameVideo(
                            imagem=imagem, indice=self._indice, t=self._relogio()
                        )
                    ultimo_ok = self._relogio()
                    self._apos_frame()
                elif self._fim_normal(lidos):
                    return True, True
                elif self._relogio() - ultimo_ok >= self._sem_frame_s:
                    break
                else:
                    self._esperar(self._pausa_falha_s)
        except Exception as e:  # nunca incluir a mensagem: pode trazer o URL com credenciais
            log.warning("fonte de vídeo falhou (%s)", type(e).__name__)
        finally:
            if captura is not None:
                captura.release()
        return False, lidos > 0

    def _ao_abrir(self, captura: Captura) -> None: ...

    def _apos_frame(self) -> None: ...

    def _fim_normal(self, lidos: int) -> bool:
        return False


class FonteRtsp(_FonteThread):
    """Câmara por RTSP/TCP. Sem frame novo há `sem_frame_s`, reabre com 1/2/4/8/10 s."""

    def __init__(self, fonte: str, *, timeout_abrir_ms: int = 5000, **kwargs: Any) -> None:
        sem_frame_s = kwargs.get("sem_frame_s", 3.0)
        kwargs.setdefault(
            "abrir",
            partial(
                abrir_rtsp,
                timeout_abrir_ms=timeout_abrir_ms,
                timeout_ler_ms=int(sem_frame_s * 1000),
            ),
        )
        super().__init__(fonte, **kwargs)


class FonteClip(_FonteThread):
    """Clip de reserva em loop, ao ritmo do ficheiro. O `indice` continua a crescer entre voltas."""

    ao_vivo = False

    def __init__(self, fonte: str, **kwargs: Any) -> None:
        kwargs.setdefault("abrir", abrir_clip)
        super().__init__(fonte, **kwargs)
        self._periodo = 1 / FPS_CLIP_OMISSAO
        self._proximo = 0.0

    def _ao_abrir(self, captura: Captura) -> None:
        fps = captura.get(cv2.CAP_PROP_FPS)
        self._periodo = 1 / (fps if 1 <= fps <= 120 else FPS_CLIP_OMISSAO)
        self._proximo = self._relogio()

    def _apos_frame(self) -> None:
        self._proximo += self._periodo
        atraso = self._proximo - self._relogio()
        if atraso > 0:
            self._esperar(atraso)
        else:  # descodificação mais lenta que o clip: não acumular dívida
            self._proximo = self._relogio()

    def _fim_normal(self, lidos: int) -> bool:
        return lidos > 0  # chegou ao fim: recomeçar já; sem frames nenhuns é falha


def criar_fonte(settings: Settings) -> FonteRtsp | FonteClip:
    """`VIDEO_SOURCE` com esquema (rtsp://...) é câmara; caso contrário é um clip local."""
    comuns = {"sem_frame_s": settings.video_sem_frame_s, "reconexao_s": settings.video_reconexao_s}
    if "://" in settings.video_source:
        return FonteRtsp(
            settings.video_source, timeout_abrir_ms=settings.video_timeout_abrir_ms, **comuns
        )
    return FonteClip(settings.video_source, **comuns)
