from fastapi import APIRouter

from homemind.core.config import get_settings
from homemind.features.engine.config import get_engine_settings
from homemind.features.health.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> Health:
    s = get_settings()
    # Só flags não sensíveis: nunca expor tokens.
    return Health(
        status="ok",
        backend=get_engine_settings().home_backend,
        physical_writes=s.enable_physical_writes,
    )
