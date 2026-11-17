import asyncio
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from homemind.contracts.video import FrameVideo
from homemind.core.config import get_settings
from homemind.features.video import service
from homemind.features.video.service import fonte_dev_permitida, partes_mjpeg
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


OPERADOR = {"x-test-sub": "sub-operador"}


def test_video_503_sem_fonte_configurada(client, monkeypatch):
    monkeypatch.delenv("VIDEO_SOURCE", raising=False)
    get_settings.cache_clear()
    try:
        resposta = client.get("/api/video", headers=OPERADOR)
    finally:
        get_settings.cache_clear()
    assert resposta.status_code == 404


def test_video_401_sem_login(client):
    assert client.get("/api/video").status_code == 401


def test_video_so_o_operador_recebe_imagens(client, monkeypatch):
    """Senhorio, inquilino e quem não tem membership: 403, mesmo com a fonte a funcionar."""
    monkeypatch.setattr(service, "_fonte", FonteFalsa())
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(video_source="x"))
    for sub in ("sub-senhorio", "sub-ana", "sub-bruno", "sub-desconhecido"):
        r = client.get("/api/video", headers={"x-test-sub": sub})
        assert r.status_code == 403, sub
        assert r.json()["error"]["code"] == "forbidden_role"


def test_video_desligado_por_omissao_mesmo_para_o_operador(client, monkeypatch):
    monkeypatch.delenv("ENABLE_DEV_VIDEO_PREVIEW", raising=False)
    get_settings.cache_clear()
    try:
        assert client.get("/api/video", headers=OPERADOR).status_code == 404
    finally:
        get_settings.cache_clear()


def test_dev_source_requires_allowlisted_local_clip(monkeypatch, tmp_path):
    from homemind.core.config import Settings

    clips = tmp_path / "privacy-test-clips"
    clips.mkdir()
    allowed = clips / "synthetic.mp4"
    allowed.write_bytes(b"synthetic placeholder, never decoded")
    monkeypatch.setattr(service, "VIDEO_TEST_CLIPS_DIR", clips)
    assert fonte_dev_permitida(
        Settings(profile="demo", video_source=str(allowed), enable_dev_video_preview=True)
    )
    assert not fonte_dev_permitida(
        Settings(
            profile="demo",
            video_source=str(tmp_path / "private.mp4"),
            enable_dev_video_preview=True,
        )
    )
    assert not fonte_dev_permitida(
        Settings(
            profile="demo",
            video_source="rtsp://user:secret@camera.invalid/live",
            enable_dev_video_preview=True,
        )
    )
    assert not fonte_dev_permitida(
        Settings(profile="normal", video_source=str(allowed), enable_dev_video_preview=True)
    )
    assert not fonte_dev_permitida(
        Settings(
            profile="demo",
            home_backend="mcp",
            video_source=str(allowed),
            enable_dev_video_preview=True,
        )
    )


def test_privacy_sensitive_configuration_defaults_fail_closed(monkeypatch):
    from homemind.core.config import Settings

    for name in (
        "PROFILE",
        "HOME_BACKEND",
        "ENABLE_DEV_VIDEO_PREVIEW",
        "PRESENCE_WIFI_COLLECTION_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.profile == "normal"
    assert settings.home_backend == "fake"
    assert settings.enable_dev_video_preview is False
    assert settings.presence_wifi_collection_enabled is False


@pytest.mark.parametrize(
    "source",
    [
        "rtsp://user:secret@camera.invalid/live",
        "http://camera.invalid/frame",
        "../../private/people.mp4",
        "arbitrary-file.mp4",
    ],
)
def test_route_never_exposes_configured_source_even_with_dev_flag(client, monkeypatch, source):
    monkeypatch.setenv("VIDEO_SOURCE", source)
    monkeypatch.setenv("ENABLE_DEV_VIDEO_PREVIEW", "true")
    get_settings.cache_clear()
    try:
        response = client.get("/api/video", headers=OPERADOR)
    finally:
        get_settings.cache_clear()
    assert response.status_code == 404


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


def test_lifespan_never_starts_configured_rtsp_source(monkeypatch):
    monkeypatch.setenv("VIDEO_SOURCE", "rtsp://camera.invalid")
    monkeypatch.delenv("VISAO_DETETOR", raising=False)
    get_settings.cache_clear()
    opened = []
    monkeypatch.setattr(
        service, "criar_fonte", lambda settings: opened.append(settings.video_source)
    )
    service.parar_fonte()
    try:
        with TestClient(app):
            assert not service.camara_ok()
        assert opened == []
    finally:
        service.parar_fonte()
        get_settings.cache_clear()


def test_rota_video_nao_aceita_flags_de_streaming(client):
    r = client.get("/api/video?anotacoes=false&esqueleto=false", headers=OPERADOR)
    assert r.status_code == 404
