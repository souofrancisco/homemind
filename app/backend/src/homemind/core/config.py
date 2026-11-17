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

    # --- P2 — gestos/presença ---
    gesto_distancia_max_ombros: float = 0.6  # × largura dos ombros (centro do objeto ao pulso)
    gesto_confianca_min: float = 0.5  # pulso, cotovelo e ombros (estritamente maior)
    gesto_janela_s: float = 1.0
    gesto_fracao_min: float = 0.8
    gesto_min_frames: int = 3  # frames válidos na janela (evita confirmar com 1-2 a fps baixo)
    gesto_cooldown_s: float = 3.0  # por classe
    presenca_ausencia_s: float = 3.0
    presenca_frames_regresso: int = 2
    visao_intervalo_max_s: float = 1.0  # buraco entre frames reais > isto reinicia janelas
    # --- fim P2 ---

    # --- P1 — visão (YOLO objetos + pose + ByteTrack; extra opcional `visao`) ---
    visao_pasta_modelos: str = "data/modelos"  # pesos .pt (ignorados pelo Git; ver pesos.py)
    visao_variante: Literal["s", "n"] = "s"  # "n" só se o FPS não chegar
    visao_modelo_objetos: str = ""  # vazio -> yolo11{variante}.pt
    visao_modelo_pose: str = ""  # vazio -> yolo11{variante}-pose.pt
    visao_conf_objetos: float = 0.4
    visao_conf_pessoa: float = 0.4
    visao_livro_coco: int = 73  # alternativas se o livro falhar: 39 garrafa, 67 telemóvel
    visao_device: str = "auto"  # auto = CUDA > MPS > CPU; ou cpu / mps / cuda:0
    visao_imgsz: int = 640
    visao_tracker: str = "bytetrack.yaml"
    # --- fim P1 — visão ---


@lru_cache
def get_settings() -> Settings:
    return Settings()
