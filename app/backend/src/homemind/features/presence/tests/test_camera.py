from datetime import UTC, datetime

import pytest

from homemind.contracts.common import Origin
from homemind.contracts.presence import VideoSourceKind as K
from homemind.contracts.video import FrameVideo
from homemind.core.config import Settings
from homemind.features.presence.camera import CameraProbe, origin_of, resolve_kind
from homemind.features.video import service as video
from homemind.features.video.fonte import FonteClip

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
SEGREDO = "rtsp://admin:segredo@10.0.0.9/stream"


class FonteFalsa:
    def __init__(self, ok=True):
        self.ok, self.frame = ok, None

    def iniciar(self): ...
    def parar(self): ...
    def ultimo_frame(self):
        return self.frame

    @property
    def camara_ok(self):
        return self.ok


def settings(fonte: str, kind: str = "") -> Settings:
    return Settings(video_source=fonte, video_source_kind=kind)


@pytest.mark.parametrize(
    ("fonte", "kind", "esperado"),
    [
        ("", "", K.clip),
        (SEGREDO, "", K.rtsp),
        (SEGREDO, "kit", K.kit),
        ("http://192.168.1.5:8080/video", "", K.phone),  # sem declarar: simulado
        ("http://192.168.1.5:8080/video", "phone", K.phone),
        ("data/porta.mp4", "", K.clip),
        ("data/porta.mp4", "kit", K.clip),  # um ficheiro nunca é a câmara real
        ("http://x/y", "rtsp", K.clip),  # nem um URL http
        (SEGREDO, "clip", K.clip),  # declarar simulado prevalece
    ],
)
def test_resolve_kind_is_restrictive(fonte, kind, esperado):
    assert resolve_kind(settings(fonte, kind)) is esperado


def test_only_kit_and_rtsp_are_real():
    assert {k for k in K if origin_of(k) is Origin.real} == {K.kit, K.rtsp}


def test_missing_or_failing_source_is_not_ok_and_has_no_fps():
    p = CameraProbe(agora=lambda: NOW)
    assert not p.status(None, K.clip).camera_ok
    f = FonteFalsa(ok=False)
    f.frame = FrameVideo(imagem=None, indice=5, t=0.0)
    s = p.status(f, K.kit)
    assert (s.camera_ok, s.fps, s.origin) == (False, None, Origin.real)


def test_fps_from_new_frames_between_polls_and_last_frame_time():
    t = {"v": 100.0}
    p = CameraProbe(relogio=lambda: t["v"], agora=lambda: NOW)
    f = FonteFalsa()
    f.frame = FrameVideo(imagem=None, indice=10, t=99.0)
    first = p.status(f, K.clip)
    assert first.fps is None and first.camera_ok
    assert first.last_frame_at == NOW.replace(second=59, minute=59, hour=11)
    t["v"], f.frame = 102.0, FrameVideo(imagem=None, indice=40, t=101.5)
    assert p.status(f, K.clip).fps == 15.0


def test_status_never_carries_image_or_url():
    f = FonteFalsa()
    f.frame = FrameVideo(imagem=b"pixels", indice=1, t=0.0)
    dump = CameraProbe(agora=lambda: NOW).status(f, K.rtsp).model_dump_json()
    assert "pixels" not in dump and "segredo" not in dump and "rtsp://" not in dump


def test_route_operator_only_and_hides_url(client, monkeypatch):
    monkeypatch.setattr(
        "homemind.features.presence.router.get_settings", lambda: settings(SEGREDO, "kit")
    )
    monkeypatch.setattr(video, "_fonte", FonteFalsa(ok=False))
    r = client.get("/api/presence/camera/status", headers={"x-test-sub": "sub-operador"})
    assert r.status_code == 200
    body = r.json()
    assert body["camera_ok"] is False and body["source"] == "kit" and body["origin"] == "real"
    assert "segredo" not in r.text
    for sub in ("sub-senhorio", "sub-ana", "sub-desconhecido"):
        r = client.get("/api/presence/camera/status", headers={"x-test-sub": sub})
        assert r.status_code == 403, sub
    assert client.get("/api/presence/camera/status").status_code == 401


def test_route_without_source_reports_not_ok_simulated(client, monkeypatch):
    monkeypatch.setattr("homemind.features.presence.router.get_settings", lambda: settings(""))
    monkeypatch.setattr(video, "_fonte", None)
    body = client.get("/api/presence/camera/status", headers={"x-test-sub": "sub-operador"}).json()
    assert (body["camera_ok"], body["origin"]) == (False, "simulated")


def test_clip_source_is_alive_without_hardware(tmp_path):
    """Fallback demonstrável sem câmara: um clip pequeno em loop dá camera_ok."""
    import time

    import cv2
    import numpy as np

    caminho = str(tmp_path / "porta.mp4")
    w = cv2.VideoWriter(caminho, cv2.VideoWriter_fourcc(*"mp4v"), 25, (64, 48))
    for i in range(10):
        w.write(np.full((48, 64, 3), i * 20, np.uint8))
    w.release()
    fonte = FonteClip(caminho, sem_frame_s=3.0)
    fonte.iniciar()
    try:
        fim = time.monotonic() + 3
        while not fonte.camara_ok and time.monotonic() < fim:
            time.sleep(0.02)
        s = CameraProbe().status(fonte, K.clip)
        assert s.camera_ok and s.origin is Origin.simulated
    finally:
        fonte.parar()
