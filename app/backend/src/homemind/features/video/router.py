from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse

from homemind.core.config import get_settings
from homemind.features.video import service
from homemind.features.video.service import LIMITE, Fonte, partes_mjpeg


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:  # a visão (alfabeticamente depois) já parou: ninguém lê a fonte
        service.parar_fonte()


router = APIRouter(prefix="/api", tags=["video"], lifespan=lifespan)


@router.get("/video", response_class=StreamingResponse)
async def video(fonte: Fonte) -> StreamingResponse:
    """MJPEG do frame mais recente, para `<img src="/api/video">`. Local, sem gravação."""
    settings = get_settings()
    return StreamingResponse(
        partes_mjpeg(
            fonte,
            fps_max=settings.video_fps_max,
            qualidade=settings.video_jpeg_qualidade,
            anotar=service.anotador,
        ),
        media_type=f"multipart/x-mixed-replace; boundary={LIMITE}",
        headers={"Cache-Control": "no-store"},
    )
