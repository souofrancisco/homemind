import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import numpy as np
from fastapi import HTTPException

from homemind.contracts.video import FonteVideo
from homemind.core.config import get_settings
from homemind.features.video.fonte import FonteClip, FonteRtsp, criar_fonte

LIMITE = "frame"
VIDEO_TEST_CLIPS_DIR = Path(__file__).resolve().parents[5] / "data" / "privacy-test-clips"

_fonte: FonteRtsp | FonteClip | None = None
_fonte_lock = threading.Lock()
log = logging.getLogger(__name__)

# Opcional: a visão regista aqui (imagem, esqueleto) -> imagem, que desenha as deteções no frame.
anotador: Callable[[np.ndarray, bool], np.ndarray] | None = None


def get_fonte() -> FonteVideo:
    """Fonte única: apenas clips de teste locais explicitamente permitidos em desenvolvimento."""
    global _fonte
    settings = get_settings()
    if not fonte_dev_permitida(settings):
        raise HTTPException(404, "Not Found")
    with _fonte_lock:
        if _fonte is None:
            _fonte = criar_fonte(settings)
            _fonte.iniciar()
        return _fonte


def fonte_atual() -> FonteVideo | None:
    """A fonte já iniciada, sem a criar nem falhar quando não está configurada."""
    return _fonte


def fonte_dev_permitida(settings=None) -> bool:
    """Aceita clips de teste dentro do diretório dedicado; RTSP e caminhos arbitrários falham."""
    settings = settings or get_settings()
    if (
        settings.profile != "demo"
        or settings.home_backend != "fake"
        or not settings.enable_dev_video_preview
        or not settings.video_source
    ):
        return False
    if "://" in settings.video_source:
        return False
    try:
        raiz = VIDEO_TEST_CLIPS_DIR.resolve(strict=True)
        fonte = Path(settings.video_source).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return fonte.is_file() and fonte.is_relative_to(raiz)


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
