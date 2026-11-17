from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from homemind.features.auth.service import current_user
from homemind.features.video import service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PRIV-02: configurar VIDEO_SOURCE não inicia qualquer captura no servidor.
    try:
        yield
    finally:
        service.parar_fonte()


router = APIRouter(prefix="/api", tags=["video"], lifespan=lifespan)


@router.get("/video", status_code=404, dependencies=[Depends(current_user)])
async def video() -> None:
    """Endpoint MJPEG legado desativado; nenhuma flag de runtime pode expor frames."""
    raise HTTPException(404, "Not Found")
