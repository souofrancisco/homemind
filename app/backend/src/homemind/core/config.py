from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_mode: Literal["simulation", "real"] = "simulation"
    database_path: str = "./data/homemind-simulation.db"
    mcp_endpoint: str = ""
    mcp_transport: str = ""
    # Nunca logar nem devolver este valor (header X-API-Key do MCP Altice).
    mcp_api_key: str = ""
    mcp_client_type: str = "core"
    # Nunca logar nem devolver este valor.
    mcp_auth_token: str = ""
    llm_api_key: str = ""
    enable_physical_writes: bool = False
    # Authentik (OIDC). Issuer = URL pública do provider (campo `iss` dos tokens);
    # jwks_url pode ser interno (ex.: http://authentik-server:9000/...) em Docker.
    oidc_issuer: str = "http://localhost:9000/application/o/homemind/"
    oidc_jwks_url: str = ""
    oidc_client_id: str = "homemind"
    # Origens dos clientes autorizados (CORS), separadas por vírgulas.
    cors_origins: str = "http://localhost:5173,http://localhost,https://localhost"
    # Vídeo: URL RTSP ou caminho de clip. Nunca logar nem devolver (pode conter credenciais).
    video_source: str = ""
    video_sem_frame_s: float = 3.0  # sem frame há mais do que isto -> camara_ok False e reabre
    video_reconexao_s: tuple[float, ...] = (1, 2, 4, 8, 10)  # esperas entre reaberturas
    video_timeout_abrir_ms: int = 5000
    video_fps_max: float = 15.0  # cadência máxima do MJPEG de GET /api/video
    video_jpeg_qualidade: int = 80


@lru_cache
def get_settings() -> Settings:
    return Settings()
