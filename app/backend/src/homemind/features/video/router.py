from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from homemind.core.config import get_settings
from homemind.features.video.service import LIMITE, Fonte, partes_mjpeg

router = APIRouter(tags=["video"])


@router.get("/video", response_class=StreamingResponse)
async def video(fonte: Fonte) -> StreamingResponse:
    """MJPEG do frame mais recente, para `<img src="/video">`. Processamento local, sem gravação."""
    settings = get_settings()
    return StreamingResponse(
        partes_mjpeg(
            fonte, fps_max=settings.video_fps_max, qualidade=settings.video_jpeg_qualidade
        ),
        media_type=f"multipart/x-mixed-replace; boundary={LIMITE}",
        headers={"Cache-Control": "no-store"},
    )
