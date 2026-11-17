import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from typing import Annotated

import numpy as np
from fastapi import Depends, HTTPException

from homemind.contracts.video import FonteVideo
from homemind.core.config import get_settings
from homemind.features.video.fonte import FonteClip, FonteRtsp, criar_fonte

LIMITE = "frame"

_fonte: FonteRtsp | FonteClip | None = None
_fonte_lock = threading.Lock()
log = logging.getLogger(__name__)

# Opcional: a visão regista aqui uma função que desenha as deteções sobre o frame.
anotador: Callable[[np.ndarray], np.ndarray] | None = None


def get_fonte() -> FonteVideo:
    """Fonte única do processo, criada e iniciada no primeiro uso."""
    global _fonte
    settings = get_settings()
    if not settings.video_source:
        raise HTTPException(503, "Fonte de vídeo não configurada")
    with _fonte_lock:
        if _fonte is None:
            _fonte = criar_fonte(settings)
            _fonte.iniciar()
        return _fonte


def parar_fonte() -> None:
    """Para e esquece a fonte, se existir. Idempotente."""
    global _fonte
    with _fonte_lock:
        fonte, _fonte = _fonte, None
    if fonte is not None:
        fonte.parar()


def camara_ok() -> bool:
    """Sinal de vida para `GET /status`. False se a fonte não está configurada ou iniciada."""
    return _fonte is not None and _fonte.camara_ok


Fonte = Annotated[FonteVideo, Depends(get_fonte)]


async def partes_mjpeg(
    fonte: FonteVideo,
    *,
    fps_max: float,
    qualidade: int,
    anotar: Callable[[np.ndarray], np.ndarray] | None = None,
) -> AsyncIterator[bytes]:
    """Uma parte multipart por frame novo; frames repetidos não são reenviados."""
    import cv2

    parametros = [cv2.IMWRITE_JPEG_QUALITY, qualidade]
    ultimo = -1
    while True:
        frame = fonte.ultimo_frame()
        if frame is None or frame.indice == ultimo:
            await asyncio.sleep(0.005)
            continue
        ultimo = frame.indice
        imagem = frame.imagem
        if anotar is not None:
            try:
                imagem = anotar(imagem)
            except Exception as e:  # nunca deixar a anotação parar o vídeo
                log.warning("anotação falhou (%s); a enviar imagem crua", type(e).__name__)
        ok, jpeg = await asyncio.to_thread(cv2.imencode, ".jpg", imagem, parametros)
        if ok:
            dados = jpeg.tobytes()
            cabecalho = (
                f"--{LIMITE}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(dados)}\r\n\r\n"
            )
            yield cabecalho.encode() + dados + b"\r\n"
        await asyncio.sleep(1 / fps_max)
