import asyncio

import cv2
import numpy as np
from fastapi.testclient import TestClient

from homemind.contracts.video import FrameVideo
from homemind.core.config import get_settings
from homemind.features.video import service
from homemind.features.video.router import video
from homemind.features.video.service import partes_mjpeg
from homemind.main import app


class FonteFalsa:
    camara_ok = True

    def __init__(self) -> None:
        self.indice = 1

    def iniciar(self) -> None: ...

    def parar(self) -> None: ...

    def ultimo_frame(self) -> FrameVideo:
        imagem = np.full((48, 64, 3), 200, dtype=np.uint8)
        return FrameVideo(imagem=imagem, indice=self.indice, t=0.0)


def test_video_503_sem_fonte_configurada(monkeypatch):
    monkeypatch.delenv("VIDEO_SOURCE", raising=False)
    get_settings.cache_clear()
    try:
        resposta = TestClient(app).get("/api/video")
    finally:
        get_settings.cache_clear()
    assert resposta.status_code == 503
    assert resposta.json()["error"]["code"] == "http_503"


def test_video_responde_multipart_mjpeg():
    resposta = asyncio.run(video(FonteFalsa()))
    assert resposta.media_type == "multipart/x-mixed-replace; boundary=frame"


def test_partes_mjpeg_emite_jpeg_valido_e_so_frames_novos():
    async def cenario():
        fonte = FonteFalsa()
        partes = partes_mjpeg(fonte, fps_max=1000, qualidade=80)
        primeira = await anext(partes)
        # Sem frame novo o gerador espera; não repete o mesmo frame.
        try:
            await asyncio.wait_for(anext(partes), timeout=0.1)
            repetiu = True
        except TimeoutError:
            repetiu = False
        return primeira, repetiu

    primeira, repetiu = asyncio.run(cenario())
    assert repetiu is False
    cabecalho, _, corpo = primeira.partition(b"\r\n\r\n")
    assert cabecalho.startswith(b"--frame\r\nContent-Type: image/jpeg")
    imagem = cv2.imdecode(np.frombuffer(corpo.rstrip(b"\r\n"), np.uint8), cv2.IMREAD_COLOR)
    assert imagem.shape == (48, 64, 3)


def _decodificar(parte: bytes) -> np.ndarray:
    _, _, corpo = parte.partition(b"\r\n\r\n")
    return cv2.imdecode(np.frombuffer(corpo.removesuffix(b"\r\n"), np.uint8), cv2.IMREAD_COLOR)


def _primeira_parte(anotar) -> bytes:
    async def cenario():
        partes = partes_mjpeg(FonteFalsa(), fps_max=1000, qualidade=95, anotar=anotar)
        return await anext(partes)

    return asyncio.run(cenario())


def test_anotador_e_aplicado_antes_de_codificar():
    imagem = _decodificar(_primeira_parte(lambda img: np.zeros_like(img)))
    assert imagem.max() < 10  # frame original é 200


def test_anotador_que_falha_envia_imagem_crua():
    def falha(img):
        raise RuntimeError("x")

    imagem = _decodificar(_primeira_parte(falha))
    assert imagem.min() > 150


def test_parar_fonte_e_idempotente():
    fonte = FonteFalsa()
    parou = []
    fonte.parar = lambda: parou.append(1)
    service._fonte = fonte
    service.parar_fonte()
    service.parar_fonte()
    assert parou == [1]
    assert service._fonte is None
