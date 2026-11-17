"""Configuração do motor (env). Local à feature para não colidir com core/config."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class EngineSettings(BaseSettings):
    profile: Literal["normal", "demo"] = "normal"
    home_backend: Literal["fake", "mcp"] = "fake"
    rules_path: Path = Path("data/rules.json")
    events_path: Path = Path("data/events.jsonl")
    # Ausência até suspender; por omissão 180 s (normal) ou 10 s (demo).
    espera_s: float | None = None
    aviso_s: float = 5
    brilho_aviso: int = 20
    suspenso_max_s: float = 30 * 60
    tarifa_eur_kwh: float = 0.16
    # Nunca logar nem devolver este valor.
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.3-70b-instruct"

    @property
    def espera(self) -> float:
        if self.espera_s is not None:
            return self.espera_s
        return 10 if self.profile == "demo" else 180


@lru_cache
def get_engine_settings() -> EngineSettings:
    return EngineSettings()
