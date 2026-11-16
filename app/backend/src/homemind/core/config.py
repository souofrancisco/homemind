from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_mode: Literal["simulation", "real"] = "simulation"
    database_path: str = "./data/homemind-simulation.db"
    mcp_endpoint: str = ""
    mcp_transport: str = ""
    # Nunca logar nem devolver este valor.
    mcp_auth_token: str = ""
    llm_api_key: str = ""
    enable_physical_writes: bool = False


def get_settings() -> Settings:
    return Settings()
