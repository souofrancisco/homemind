from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import StreamingResponse

from homemind.core.config import get_settings
from homemind.features.auth.service import current_user
from homemind.features.video import service
from homemind.features.video.service import LIMITE, Fonte, partes_mjpeg


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Captura independente do YOLO: sem isto `camera_ok` só subia após o primeiro GET /api/video,
    # que o frontend só pede com `camera_ok=true`.
    if get_settings().video_source:
        service.get_fonte()
    try:
        yield
    finally:  # a visão (alfabeticamente depois) já parou: ninguém lê a fonte
        service.parar_fonte()


router = APIRouter(prefix="/api", tags=["video"], lifespan=lifespan)


# Bearer obrigatório: o frontend usa fetch (um <img> não envia cabeçalhos; token nunca no URL).
@router.get("/video", response_class=StreamingResponse, dependencies=[Depends(current_user)])
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
