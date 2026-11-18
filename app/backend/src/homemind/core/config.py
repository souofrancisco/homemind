from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    profile: Literal["normal", "demo"] = "normal"
    home_backend: Literal["fake", "mcp"] = "fake"
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
    # ALERT-06: divisão (`room.id`) onde está a lâmpada do kit, na casa ENERGY_HOUSEHOLD_ID. Sem
    # ela a lâmpada não tem divisão conhecida e nunca recebe a cor do orçamento (mais restritivo).
    mcp_lamp_room_id: UUID | None = None
    # Unidade de `instantPower` quando o MCP não a declara (o kit real não declara). Vazio =
    # desconhecida: consumo_w fica null. Confirmar com carga conhecida (docs/mcp-capabilities.md).
    mcp_instantpower_unit: Literal["", "W", "dW", "mW"] = ""
    energy_household_id: UUID | None = None
    enable_physical_writes: bool = False
    # SQLite partilhado (eventos, casas, memberships). Ficheiro local; ":memory:" nos testes.
    db_path: str = "data/homemind.sqlite3"
    db_busy_timeout_ms: int = 5000
    # PRIV-04: dias que a telemetria em bruto (leituras de energia e sensores) e os agregados
    # diários dos alertas ficam guardados. 0 = sem expurgo. Mínimo 62: o mês corrente e o
    # anterior têm de estar completos (totais de energia, fecho da fatura). PROPOSTA (P-08).
    retention_telemetry_days: int = 90
    # PRIV-04: anonimizar um ex-morador N dias depois de o último contrato acabar (nome, conta,
    # email do convite, conversa e notificações pessoais; os valores financeiros ficam).
    # 0 = DESLIGADO (omissão) até a equipa/DPO fixar o prazo (P-08); se ligado, mínimo 30.
    retention_anonymize_after_days: int = 0
    # Authentik (OIDC). Issuer = URL pública do provider (campo `iss` dos tokens);
    # jwks_url pode ser interno (ex.: http://authentik-server:9000/...) em Docker.
    oidc_issuer: str = "http://localhost:9000/application/o/homemind/"
    oidc_jwks_url: str = ""
    oidc_client_id: str = "homemind"
    # Origens dos clientes autorizados (CORS), separadas por vírgulas.
    cors_origins: str = "http://localhost:5173,http://localhost,https://localhost"
    # Fonte legado: serviço só aceita clip de teste allowlisted em demo; nunca logar/devolver path.
    video_source: str = ""
    # Que fonte é (PRES-01): kit | rtsp | clip | phone. Vazio = deduzir do URL (rtsp:// -> rtsp;
    # http(s):// -> phone, SIMULADO; sem esquema -> clip, SIMULADO). Nunca promove a «real».
    video_source_kind: Literal["", "kit", "rtsp", "clip", "phone"] = ""
    # PRIV-02: flag adicional para processamento de clips sintéticos permitidos em PROFILE=demo.
    # Não reabre o endpoint MJPEG, que permanece desativado.
    enable_dev_video_preview: bool = False
    # Pista individual por Wi-Fi: sem recolha antes de revisão e ativação explícita.
    presence_wifi_collection_enabled: bool = False
    video_sem_frame_s: float = 3.0  # sem frame há mais do que isto -> camara_ok False e reabre
    video_reconexao_s: tuple[float, ...] = (1, 2, 4, 8, 10)  # esperas entre reaberturas
    video_timeout_abrir_ms: int = 5000
    video_fps_max: float = 15.0  # cadência máxima do MJPEG de GET /api/video
    video_jpeg_qualidade: int = 80

    # --- P2 — porta (PRES-02). Coordenadas normalizadas 0–1 "x1,y1,x2,y2"; vazio = desligado ---
    presence_household_id: str = ""  # casa a que pertencem os eventos da porta (UUID)
    presence_detetor: str = (
        ""  # modulo:Classe; YOLO real: homemind.features.presence.yolo:DetetorYoloPessoas
    )
    presence_door_roi: str = ""  # retângulo da soleira; o YOLO só recebe este recorte
    presence_door_line: str = ""  # linha orientada (início -> fim) dentro da soleira
    presence_door_inside_sign: int = 1  # 1 ou -1; sinal do lado de DENTRO (ver door.py)
    presence_door_cooldown_s: float = Field(
        default=1.0, ge=0
    )  # mesmo sentido: 2.ª contagem ignorada
    presence_door_confirm_s: float = Field(
        default=1.0, ge=0
    )  # cruzamento reverso anula dentro disto
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

    # --- P2 — presença (PRES-03/04) ---
    # Sal do `match_key` dos telemóveis (hash do MAC). Segredo: só em app/.env, nunca em logs.
    # Vazio = registo de telemóveis e pistas Wi-Fi desligados (falha fechada).
    # Pista individual por Wi-Fi: sem recolha antes de ativação explícita (alinhado com o PRIV-02).
    presence_wifi_collection_enabled: bool = False
    presence_match_salt: str = ""
    # Origem das observações Wi-Fi: off | simulated (SIMULADO, MACs fictícios abaixo) | arp (varre
    # a sub-rede a partir deste processo) | ingest (um varrimento no anfitrião publica hashes).
    presence_wifi_mode: Literal["off", "simulated", "arp", "ingest"] = "off"
    presence_wifi_subnet: str = ""  # ex.: 192.168.1.0/24 (rede do hub do kit; só redes privadas)
    presence_wifi_interval_s: float = Field(default=30.0, ge=10.0)
    presence_wifi_sim_addresses: str = ""  # modo simulated: MACs fictícios «vistos», por vírgulas
    # Token do varrimento no anfitrião (modo ingest). Vazio = rota desligada.
    presence_ingest_token: str = ""
    # Fusão (PRES-04): minutos sem pistas, depois de uma saída pela porta, até «fora» (20–30).
    presence_tolerance_min: float = Field(default=25.0, ge=20.0, le=30.0)
    # Um aparelho pessoal só prova presença se LIGOU há menos de isto (s); já ligado não prova.
    presence_appliance_fresh_s: float = Field(default=300.0, ge=0.0)
    presence_fusion_tick_s: float = Field(default=30.0, ge=1.0)
    # --- fim P2 — presença ---

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

    @field_validator("retention_telemetry_days")
    @classmethod
    def _retencao(cls, v: int) -> int:
        if v != 0 and v < 62:
            raise ValueError("RETENTION_TELEMETRY_DAYS é 0 (sem expurgo) ou pelo menos 62")
        return v

    @field_validator("retention_anonymize_after_days")
    @classmethod
    def _anonimizar(cls, v: int) -> int:
        if v != 0 and v < 30:
            raise ValueError("RETENTION_ANONYMIZE_AFTER_DAYS é 0 (desligado) ou pelo menos 30")
        return v

    @field_validator("presence_door_inside_sign")
    @classmethod
    def _sinal(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("PRESENCE_DOOR_INSIDE_SIGN é 1 ou -1")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
