"""Presença (P2). IMPLEMENTADO: estado da câmara (PRES-01) e contagem na porta (PRES-02).
PLANEADO: o resto (PRES-03…06)."""

import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI

from homemind.contracts.presence import CameraStatus
from homemind.core.access import require_operator
from homemind.core.config import get_settings
from homemind.features.presence.camera import CameraProbe, origin_of, resolve_kind
from homemind.features.presence.door import ContadorPorta, Soleira, parse_retangulo
from homemind.features.presence.runner import (
    ProcessadorPorta,
    ThreadPorta,
    carregar_detetor_pessoas,
)
from homemind.features.video import service as video

log = logging.getLogger(__name__)


def soleira_configurada() -> Soleira | None:
    """Soleira de `PRESENCE_DOOR_ROI`/`_LINE`; None se não houver (ou for inválida)."""
    s = get_settings()
    try:
        roi, linha = parse_retangulo(s.presence_door_roi), parse_retangulo(s.presence_door_line)
        if roi is None or linha is None:
            return None
        return Soleira(roi=roi, linha=linha, sinal_interior=s.presence_door_inside_sign)
    except ValueError as e:
        log.error("soleira inválida (%s): porta desligada", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Liga a contagem da porta só com fonte, casa, soleira e detetor configurados."""
    s = get_settings()
    soleira = soleira_configurada()
    if not (s.video_source and s.presence_household_id and s.presence_detetor and soleira):
        log.info("contagem da porta desligada: falta fonte, casa, soleira e/ou detetor")
        yield
        return
    try:
        casa = UUID(s.presence_household_id)
        detetor = carregar_detetor_pessoas(s.presence_detetor)
    except ValueError as e:
        log.error("contagem da porta desligada (%s)", e)
        yield
        return
    bus = app.state.bus

    def publicar(evento) -> None:
        try:
            bus.publish_threadsafe(evento)
        except Exception as e:  # casa inexistente, base fechada...: nunca o conteúdo
            log.error("evento da porta não gravado (%s)", type(e).__name__)

    processador = ProcessadorPorta(
        soleira,
        detetor,
        ContadorPorta(
            soleira, cooldown_s=s.presence_door_cooldown_s, confirmar_s=s.presence_door_confirm_s
        ),
        publicar,
        casa,
        origin_of(resolve_kind(s)),
    )
    thread = ThreadPorta(video.get_fonte(), processador)
    thread.iniciar()
    log.info("contagem da porta ligada")
    try:
        yield
    finally:
        thread.parar()


router = APIRouter(prefix="/api/presence", tags=["presence"], lifespan=lifespan)

_probe = CameraProbe()


@router.get("/camera/status", dependencies=[Depends(require_operator)])
async def camera_status() -> CameraStatus:
    """Diagnóstico da câmara da porta: fonte, origem (real/simulada), vida e FPS. Sem imagem
    nem URL. Fonte em falha ou ausente: `camera_ok=false`, nunca «casa vazia»."""
    return _probe.status(
        video.fonte_atual(),
        resolve_kind(get_settings()),
        door_mask_configured=soleira_configurada() is not None,
    )
