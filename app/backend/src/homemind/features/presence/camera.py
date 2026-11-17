"""Estado da câmara da porta (PRES-01): que fonte é, se é real ou simulada, se está viva.

Só diagnóstico: nunca devolve imagem nem URL (pode ter credenciais). Fonte indisponível é
`camera_ok=false`; nunca significa «casa vazia».
"""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from homemind.contracts.common import Origin
from homemind.contracts.presence import CameraStatus, VideoSourceKind
from homemind.contracts.video import FonteVideo
from homemind.core.config import Settings

_REAIS = (VideoSourceKind.kit, VideoSourceKind.rtsp)


def resolve_kind(settings: Settings) -> VideoSourceKind:
    """Tipo da fonte. Em dúvida, a mais restritiva: SIMULADA.

    - Sem fonte configurada: `clip` (simulada), com `camera_ok=false`.
    - `kit`/`rtsp` só valem com um URL de rede por RTSP; um caminho local é um clip.
    - Sem `VIDEO_SOURCE_KIND`, só `rtsp://` conta como câmara real; `http(s)://` é telemóvel.
    """
    fonte = settings.video_source.strip()
    if not fonte:
        return VideoSourceKind.clip
    esquema = fonte.split("://", 1)[0].lower() if "://" in fonte else ""
    declarado = settings.video_source_kind
    if declarado:
        tipo = VideoSourceKind(declarado)
        if tipo in _REAIS and esquema not in ("rtsp", "rtsps"):
            return VideoSourceKind.clip
        return tipo
    if esquema in ("rtsp", "rtsps"):
        return VideoSourceKind.rtsp
    return VideoSourceKind.phone if esquema in ("http", "https") else VideoSourceKind.clip


def origin_of(kind: VideoSourceKind) -> Origin:
    return Origin.real if kind in _REAIS else Origin.simulated


class CameraProbe:
    """Calcula o estado a partir da fonte. O FPS é a cadência de frames novos entre duas
    consultas (None na primeira). Os frames não saem daqui: só `indice` e `t`."""

    def __init__(
        self,
        *,
        relogio: Callable[[], float] = time.monotonic,
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._relogio = relogio
        self._agora = agora
        self._lock = threading.Lock()
        self._anterior: tuple[int, float] | None = None  # (indice, instante da consulta)

    def status(
        self,
        fonte: FonteVideo | None,
        kind: VideoSourceKind,
        *,
        door_mask_configured: bool = False,
    ) -> CameraStatus:
        origin = origin_of(kind)
        frame = fonte.ultimo_frame() if fonte is not None else None
        ok = fonte is not None and fonte.camara_ok
        t_agora = self._relogio()
        fps: float | None = None
        with self._lock:
            if ok and frame is not None:
                if self._anterior is not None:
                    dt = t_agora - self._anterior[1]
                    if dt > 0:
                        fps = min(120.0, max(0.0, (frame.indice - self._anterior[0]) / dt))
                self._anterior = (frame.indice, t_agora)
            else:
                self._anterior = None
        ultimo = None
        if frame is not None:
            ultimo = self._agora() - timedelta(seconds=max(0.0, t_agora - frame.t))
        return CameraStatus(
            source=kind,
            origin=origin,
            camera_ok=ok,
            fps=round(fps, 1) if fps is not None else None,
            last_frame_at=ultimo,
            door_mask_configured=door_mask_configured,
        )
