"""Presença (P2). IMPLEMENTADO: estado da câmara (PRES-01). PLANEADO: o resto (PRES-02…06)."""

from fastapi import APIRouter, Depends

from homemind.contracts.presence import CameraStatus
from homemind.core.access import require_operator
from homemind.core.config import get_settings
from homemind.features.presence.camera import CameraProbe, resolve_kind
from homemind.features.video import service as video

router = APIRouter(prefix="/api/presence", tags=["presence"])

_probe = CameraProbe()


@router.get("/camera/status", dependencies=[Depends(require_operator)])
async def camera_status() -> CameraStatus:
    """Diagnóstico da câmara da porta: fonte, origem (real/simulada), vida e FPS. Sem imagem
    nem URL. Fonte em falha ou ausente: `camera_ok=false`, nunca «casa vazia»."""
    return _probe.status(video.fonte_atual(), resolve_kind(get_settings()))
