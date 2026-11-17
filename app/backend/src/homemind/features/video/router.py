from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from homemind.core.config import get_settings
from homemind.features.auth.service import current_user
from homemind.features.video.service import LIMITE, Fonte, partes_mjpeg

router = APIRouter(prefix="/api", tags=["video"])


# Bearer obrigatório: o frontend usa fetch (um <img> não envia cabeçalhos; token nunca no URL).
@router.get("/video", response_class=StreamingResponse, dependencies=[Depends(current_user)])
async def video(fonte: Fonte) -> StreamingResponse:
    """MJPEG do frame mais recente, para `<img src="/api/video">`. Local, sem gravação."""
    settings = get_settings()
    return StreamingResponse(
        partes_mjpeg(
            fonte, fps_max=settings.video_fps_max, qualidade=settings.video_jpeg_qualidade
        ),
        media_type=f"multipart/x-mixed-replace; boundary={LIMITE}",
        headers={"Cache-Control": "no-store"},
    )
