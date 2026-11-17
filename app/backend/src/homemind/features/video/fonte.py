"""Leitura de vídeo (RTSP/TCP via OpenCV+FFmpeg) que mantém só o frame mais recente.

Os frames vivem em memória e são substituídos; nada é gravado, enfileirado ou registado.
O URL da fonte pode conter credenciais: nunca o escrever em logs ou erros.
"""

import os
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from homemind.contracts.video import FrameVideo


class Captura(Protocol):
    def read(self) -> tuple[bool, Any]: ...

    def release(self) -> None: ...


def abrir_captura(fonte: str) -> Captura:
    import cv2

    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    captura = cv2.VideoCapture(fonte, cv2.CAP_FFMPEG)
    captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return captura


class FonteRtsp:
    """Implementa `homemind.contracts.video.FonteVideo`."""

    def __init__(
        self,
        fonte: str,
        *,
        sem_frame_s: float = 3.0,
        abrir: Callable[[str], Captura] = abrir_captura,
        relogio: Callable[[], float] = time.monotonic,
        pausa_falha_s: float = 0.05,
    ) -> None:
        self._fonte = fonte
        self._sem_frame_s = sem_frame_s
        self._abrir = abrir
        self._relogio = relogio
        self._pausa_falha_s = pausa_falha_s
        self._lock = threading.Lock()
        self._frame: FrameVideo | None = None
        self._indice = 0
        self._parar = threading.Event()
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

    def _ciclo(self) -> None:
        # Abrir aqui e não em iniciar(): a ligação RTSP pode demorar e não deve bloquear a API.
        captura = self._abrir(self._fonte)
        try:
            while not self._parar.is_set():
                ok, imagem = captura.read()
                if not ok:
                    self._parar.wait(self._pausa_falha_s)
                    continue
                with self._lock:
                    self._indice += 1
                    self._frame = FrameVideo(imagem=imagem, indice=self._indice, t=self._relogio())
        finally:
            captura.release()
