from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mcp_endpoint: str = ""
    # Nunca logar nem devolver este valor (header X-API-Key do MCP Altice).
    mcp_api_key: str = ""
    mcp_client_type: str = "core"
    mcp_poll_seconds: float = Field(default=5.0, ge=1.0)
    mcp_poll_backoff_max_s: float = 60.0
    mcp_oauth_client_id: str = "mcp-client"
    mcp_oauth_callback_port: int = 5434
    mcp_oauth_callback_url: str = "http://mcp-redirect.futurelabsinnovations.com:5434/callback"
    # Tokens MCP ficam fora do código, numa diretoria 0700 montada no container (não o ficheiro:
    # a escrita atómica com os.replace falha em bind mounts de ficheiros).
    mcp_token_path: Path = Path(__file__).resolve().parents[4] / ".mcp-auth" / "tokens.json"
    # Autorização temporária de escritas físicas (ficheiro de grant) e IDs opcionais da demo.
    mcp_write_grant_path: Path = Path("data/mcp-write-grant.json")
    mcp_write_max_minutes: int = 60
    mcp_lamp_id: str = ""
    mcp_plug_id: str = ""
    # Unidade de `instantPower` quando o MCP não a declara (o kit real não declara). Vazio =
    # desconhecida: consumo_w fica null. Confirmar com carga conhecida (docs/mcp-capabilities.md).
    mcp_instantpower_unit: Literal["", "W", "dW", "mW"] = ""
    enable_physical_writes: bool = False
    # SQLite partilhado (eventos, casas, memberships). Ficheiro local; ":memory:" nos testes.
    db_path: str = "data/homemind.sqlite3"
    db_busy_timeout_ms: int = 5000
    # Authentik (OIDC). Issuer = URL pública do provider (campo `iss` dos tokens);
    # jwks_url pode ser interno (ex.: http://authentik-server:9000/...) em Docker.
    oidc_issuer: str = "http://localhost:9000/application/o/homemind/"
    oidc_jwks_url: str = ""
    oidc_client_id: str = "homemind"
    # Origens dos clientes autorizados (CORS), separadas por vírgulas.
    cors_origins: str = "http://localhost:5173,http://localhost,https://localhost"
    # Vídeo: URL RTSP ou caminho de clip. Nunca logar nem devolver (pode conter credenciais).
    video_source: str = ""
    # PRIV-02: o endpoint MJPEG herdado só pode servir clips locais em desenvolvimento.
    # Nunca permitir preview de uma stream RTSP real; fechado por omissão.
    enable_dev_video_preview: bool = False
    # Pista individual por Wi-Fi: sem recolha antes de revisão e ativação explícita.
    presence_wifi_collection_enabled: bool = False
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
