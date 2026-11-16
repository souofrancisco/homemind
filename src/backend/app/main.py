from fastapi import FastAPI

from app.core.config import get_settings

app = FastAPI(title="HomeMind Spaces API")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    s = get_settings()
    # Só flags não sensíveis: nunca expor tokens.
    return {"status": "ok", "mode": s.app_mode, "physical_writes": s.enable_physical_writes}
