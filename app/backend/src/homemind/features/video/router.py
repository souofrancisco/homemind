from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import StreamingResponse

from homemind.contracts.video import FonteVideo
from homemind.core.access import require_operator
from homemind.core.config import get_settings
from homemind.features.video import service
from homemind.features.video.service import LIMITE, get_fonte, partes_mjpeg


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PRIV-02: configurar VIDEO_SOURCE não inicia qualquer captura no servidor.
    try:
        yield
    finally:
        service.parar_fonte()


Fonte = Annotated[FonteVideo, Depends(get_fonte)]  # 404 salvo clip dev permitido (PRIV-02)

router = APIRouter(prefix="/api", tags=["video"], lifespan=lifespan)


# Só o operador (diagnóstico): senhorio e moradores nunca recebem imagens. Bearer obrigatório:
# o frontend usa fetch (um <img> não envia cabeçalhos; token nunca no URL).
@router.get("/video", response_class=StreamingResponse, dependencies=[Depends(require_operator)])
async def video(fonte: Fonte, anotacoes: bool = True, esqueleto: bool = True) -> StreamingResponse:
    """MJPEG do frame mais recente, para `<img src="/api/video">`. Local, sem gravação.

    `anotacoes=false` → imagem limpa; `esqueleto=false` → só caixas. A inferência é única (thread
    de visão); cada espectador só desenha sobre o frame que lê.
    """
    settings = get_settings()
    anotador = service.anotador
    anotar = (lambda img: anotador(img, esqueleto)) if anotacoes and anotador else None
    return StreamingResponse(
        partes_mjpeg(
            fonte,
            fps_max=settings.video_fps_max,
            qualidade=settings.video_jpeg_qualidade,
            anotar=anotar,
        ),
        media_type=f"multipart/x-mixed-replace; boundary={LIMITE}",
        headers={"Cache-Control": "no-store"},
    )
