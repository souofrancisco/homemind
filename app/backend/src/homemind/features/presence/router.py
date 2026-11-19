"""Presença (P2). IMPLEMENTADO: estado da câmara (PRES-01), contagem na porta (PRES-02) e
telemóveis com opt-in e pistas Wi-Fi (PRES-03).

Todas as rotas levam `?household_id=` e exigem inquilino com membership ativa: o senhorio e o
operador recebem `403 forbidden_role`, quem não é membro `404 household_not_found`. A identidade
vem sempre da sessão, nunca do pedido. A rota de observações do varrimento no anfitrião é a única
sem utilizador (token de máquina) e não entra no contrato OpenAPI.
"""

import asyncio
import hmac
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import Field

from homemind.contracts.common import ContractModel, Origin, ShortText
from homemind.contracts.presence import (
    CameraStatus,
    ConsentSource,
    HouseOccupancy,
    PersonPresence,
    PresenceConsentIn,
    PresenceConsentsView,
    PresenceDeviceView,
    PresenceSourceRevocationView,
)
from homemind.core.access import (
    HouseholdAccess,
    Operation,
    Resource,
    get_clock,
    require_access,
    require_operator,
)
from homemind.core.config import get_settings
from homemind.core.events import EventBus
from homemind.features.presence import consent
from homemind.features.presence.camera import CameraProbe, origin_of, resolve_kind
from homemind.features.presence.door import ContadorPorta, Soleira, parse_retangulo
from homemind.features.presence.export import PresenceExport, export_own
from homemind.features.presence.fusion import FusionParams
from homemind.features.presence.retention import compact, erase_unconsented
from homemind.features.presence.runner import (
    ProcessadorPorta,
    ThreadPorta,
    carregar_detetor_pessoas,
)
from homemind.features.presence.service import (
    DeviceError,
    PresenceService,
    WifiPoller,
    on_notification_responded,
)
from homemind.features.presence.wifi import (
    ArpScanner,
    FakeWifiScanner,
    WifiConfigError,
    WifiScanner,
)
from homemind.features.video import service as video

log = logging.getLogger(__name__)

Read = Annotated[HouseholdAccess, Depends(require_access(Resource.presence))]
Write = Annotated[HouseholdAccess, Depends(require_access(Resource.presence, Operation.write))]


def _scanner_for(mode: str, s) -> WifiScanner | None:
    if mode == "simulated":
        addrs = [a for a in s.presence_wifi_sim_addresses.split(",") if a.strip()]
        return FakeWifiScanner(addrs)
    if mode == "arp":
        return ArpScanner(s.presence_wifi_subnet)
    return None  # off, ou ingest (o varrimento corre no anfitrião)


def _camera_state() -> tuple[bool, Origin]:
    """Câmara ativa e origem (clip/telemóvel = SIMULADO). Fonte em falha ou ausente: inativa."""
    fonte = video.fonte_atual()
    return (
        fonte is not None and fonte.camara_ok,
        origin_of(resolve_kind(get_settings())),
    )


async def _ticker(service: PresenceService, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await service.tick()
        except Exception as e:  # noqa: BLE001 - o ciclo não pode morrer
            log.error("reavaliação de presença falhou (%s)", type(e).__name__)


def soleira_configurada() -> Soleira | None:
    """Soleira de `PRESENCE_DOOR_ROI`/`_LINE`; None se não houver (ou for inválida)."""
    s = get_settings()
    try:
        roi, linha = parse_retangulo(s.presence_door_roi), parse_retangulo(s.presence_door_line)
        if roi is None or linha is None:
            return None
        return Soleira(roi=roi, linha=linha, sinal_interior=s.presence_door_inside_sign)
    except ValueError as e:
        log.error("soleira inválida (%s): porta desligada", e)
        return None


@asynccontextmanager
async def _wifi_lifespan(app: FastAPI):
    s = get_settings()
    bus: EventBus = app.state.bus
    wifi_on = s.presence_wifi_mode != "off" and bool(s.presence_match_salt)
    service = PresenceService(
        app.state.db,
        bus,
        salt=s.presence_match_salt,
        clock=get_clock(),
        fusion=FusionParams(tolerance=timedelta(minutes=s.presence_tolerance_min)),
        appliance_fresh_s=s.presence_appliance_fresh_s,
        wifi_enabled=wifi_on,
        wifi_interval_s=s.presence_wifi_interval_s,
        camera_state=_camera_state,
    )
    app.state.presence = service
    bus.subscribe("presence.answers", on_notification_responded, types=["notification.responded"])
    bus.subscribe(
        "presence.appliance", service.on_consumption_detected, types=["energy.consumption_detected"]
    )
    bus.subscribe(
        "presence.fusion",
        service.on_presence_input,
        types=["presence.cue_recorded", "presence.door_crossed"],
    )
    ticker = asyncio.create_task(_ticker(service, s.presence_fusion_tick_s), name="presence-tick")
    poller_task = None
    if not s.presence_wifi_collection_enabled:
        if s.presence_wifi_mode != "off":
            log.warning("Wi-Fi de presença desligado: PRESENCE_WIFI_COLLECTION_ENABLED=false")
    elif s.presence_wifi_mode != "off" and not s.presence_match_salt:
        log.error("Wi-Fi de presença desligado: falta PRESENCE_MATCH_SALT")
    elif s.presence_wifi_mode in ("simulated", "arp"):
        try:
            scanner = _scanner_for(s.presence_wifi_mode, s)
        except WifiConfigError as e:
            log.error("Wi-Fi de presença desligado: %s", e)
            scanner = None
        if scanner is not None:
            poller = WifiPoller(service, scanner, s.presence_wifi_interval_s)
            poller_task = asyncio.create_task(poller.run(), name="presence-wifi")
            log.info("Wi-Fi de presença ligado (modo %s)", s.presence_wifi_mode)
    try:
        yield
    finally:
        tasks = [t for t in (poller_task, ticker) if t is not None]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def _door_lifespan(app: FastAPI):
    """Liga a contagem da porta só com fonte, casa, soleira e detetor configurados."""
    s = get_settings()
    soleira = soleira_configurada()
    if not (s.video_source and s.presence_household_id and s.presence_detetor and soleira):
        log.info("contagem da porta desligada: falta fonte, casa, soleira e/ou detetor")
        yield
        return
    try:
        casa = UUID(s.presence_household_id)
        detetor = carregar_detetor_pessoas(s.presence_detetor)
    except ValueError as e:
        log.error("contagem da porta desligada (%s)", e)
        yield
        return
    bus = app.state.bus

    def publicar(evento) -> None:
        try:
            bus.publish_threadsafe(evento)
        except Exception as e:  # casa inexistente, base fechada...: nunca o conteúdo
            log.error("evento da porta não gravado (%s)", type(e).__name__)

    processador = ProcessadorPorta(
        soleira,
        detetor,
        ContadorPorta(
            soleira, cooldown_s=s.presence_door_cooldown_s, confirmar_s=s.presence_door_confirm_s
        ),
        publicar,
        casa,
        origin_of(resolve_kind(s)),
    )
    thread = ThreadPorta(video.get_fonte(), processador)
    thread.iniciar()
    log.info("contagem da porta ligada")
    try:
        yield
    finally:
        thread.parar()


RETENTION_FIRST_RUN_S = 60.0
RETENTION_INTERVAL_S = 600.0


@asynccontextmanager
async def _retention_lifespan(app: FastAPI):
    """PRIV-03: elimina os dados de quem revogou o opt-in ou saiu da casa e compacta os eventos
    brutos antigos em agregados diários. Uma falha só deixa o tipo no log; tenta-se no ciclo
    seguinte. A eliminação corre sempre; a compactação desliga-se com
    `PRESENCE_RETENTION_DAYS=0`."""
    days = get_settings().presence_retention_days

    async def loop() -> None:
        await asyncio.sleep(RETENTION_FIRST_RUN_S)
        while True:
            now = app.state.presence.clock()
            try:
                erased = await asyncio.to_thread(erase_unconsented, app.state.db.run_sync, now)
                if erased.residents:
                    log.info("presença: dados de %d morador(es) eliminados", erased.residents)
                done = await asyncio.to_thread(compact, app.state.db.run_sync, now, days)
                if done:
                    log.info(
                        "presença: %d eventos brutos compactados em %d dia(s)",
                        done.events,
                        done.days,
                    )
            except Exception as e:  # nunca derruba o servidor; tenta no próximo ciclo
                log.warning("presença: retenção falhou (%s)", type(e).__name__)
            await asyncio.sleep(RETENTION_INTERVAL_S)

    task = asyncio.create_task(loop(), name="presence-retention")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_wifi_lifespan(app))
        await stack.enter_async_context(_retention_lifespan(app))
        await stack.enter_async_context(_door_lifespan(app))
        yield


router = APIRouter(prefix="/api/presence", tags=["presence"], lifespan=lifespan)


def get_service(request: Request) -> PresenceService:
    return request.app.state.presence


Service = Annotated[PresenceService, Depends(get_service)]


def _http(e: DeviceError) -> HTTPException:
    table = {
        "wifi_unconfigured": (503, "Presença por Wi-Fi não configurada"),
        "invalid_address": (400, "Endereço de rede inválido"),
        "device_limit": (409, "Número máximo de telemóveis atingido"),
        "device_already_registered": (409, "Telemóvel já registado"),
        "presence_opt_in_required": (
            409,
            "Ativa primeiro a partilha da tua presença para poderes ligar uma fonte",
        ),
        "text_version_outdated": (
            409,
            "O texto do consentimento mudou: lê a versão atual e confirma outra vez",
        ),
    }
    status, message = table.get(e.code, (400, "Pedido inválido"))
    return HTTPException(status, {"code": e.code, "message": message})


@router.get("")
async def get_presence(access: Read, service: Service) -> PersonPresence:
    """O meu estado. Ninguém mais o vê (nem colegas, nem senhorio, nem operador)."""
    return await service.own_state(access.household_id, access.resident_id)


@router.get("/export")
async def export_my_data(access: Read, service: Service) -> PresenceExport:
    """Todos os MEUS dados de presença nesta casa (PRIV-03). Nunca os de colegas, nem o senhorio."""
    now = service.clock()
    days = get_settings().presence_retention_days
    return await service.db.run(
        lambda c: export_own(c, access.household_id, access.resident_id, now, days)
    )


@router.get("/consents")
async def get_consents(access: Read, service: Service) -> PresenceConsentsView:
    """O MEU consentimento por fonte (Wi-Fi, aparelho a ligar, resposta manual), o texto de cada
    uma e o meu registo. Desligado por omissão. Só o próprio; senhorio e operador recebem 403."""
    now = service.clock()
    return await service.db.run(
        lambda c: consent.build_view(c, access.household_id, access.resident_id, now)
    )


@router.post("/consents/{source}")
async def grant_consent(
    source: ConsentSource, body: PresenceConsentIn, access: Write, service: Service
) -> PresenceConsentsView:
    """Liga UMA fonte com a versão do texto que o morador viu (idempotente)."""
    try:
        await service.grant_source(
            access.household_id, access.resident_id, source, body.text_version
        )
    except DeviceError as e:
        raise _http(e) from e
    return await get_consents(access, service)


@router.delete("/consents/{source}")
async def revoke_consent(
    source: ConsentSource, access: Write, service: Service
) -> PresenceSourceRevocationView:
    """Desliga UMA fonte e apaga só os dados dessa fonte (idempotente). Devolve contagens."""
    cues, other = await service.revoke_source(access.household_id, access.resident_id, source)
    return PresenceSourceRevocationView(source=source, erased_cues=cues, erased_other=other)


@router.get("/occupancy")
async def get_occupancy(access: Read, service: Service) -> HouseOccupancy:
    """Quantas pessoas estão em casa e quantas são visitas: só números, sem identidade nem
    horários. O senhorio e o operador recebem 403. Sem câmara a funcionar, ou com contagem que
    diverge dos telemóveis, o estado é `uncertain` (nunca «casa vazia», nunca negativo)."""
    camera_ok, origin = _camera_state()
    return await service.occupancy(access.household_id, camera_ok=camera_ok, camera_origin=origin)


class PresenceDeviceIn(ContractModel):
    """Registo de um telemóvel. `consent` tem de ser `true`: o opt-in é explícito. O endereço de
    rede só serve para calcular o hash e nunca é guardado nem devolvido."""

    label: ShortText
    wifi_address: Annotated[str, Field(min_length=11, max_length=17, repr=False)]
    consent: Literal[True]


@router.get("/devices")
async def list_devices(access: Read, service: Service) -> list[PresenceDeviceView]:
    devices = await service.list_devices(access.household_id, access.resident_id)
    return [PresenceDeviceView.of(d) for d in devices]


@router.post("/devices", status_code=201)
async def register_device(
    body: PresenceDeviceIn, access: Write, service: Service
) -> PresenceDeviceView:
    try:
        device = await service.register_device(
            access.household_id, access.resident_id, body.label, body.wifi_address
        )
    except DeviceError as e:
        raise _http(e) from e
    return PresenceDeviceView.of(device)


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(device_id: UUID, access: Write, service: Service) -> Response:
    """Opt-out imediato: o telemóvel deixa de ser reconhecido e o seu hash é apagado."""
    if not await service.revoke_device(access.household_id, access.resident_id, device_id):
        raise HTTPException(
            404, {"code": "device_not_found", "message": "Telemóvel não encontrado"}
        )
    return Response(status_code=204)


Key = Annotated[str, Field(min_length=16, max_length=128)]


class WifiObservations(ContractModel):
    """Hashes (já calculados no anfitrião) dos aparelhos vistos. Nunca MACs."""

    keys: Annotated[
        list[Annotated[str, Field(min_length=16, max_length=128)]], Field(max_length=512)
    ]


@router.post("/wifi/observations", status_code=204, include_in_schema=False)
async def wifi_observations(
    body: WifiObservations,
    service: Service,
    x_presence_token: Annotated[str | None, Header()] = None,
) -> Response:
    """Varrimento no anfitrião (o contentor não vê a ARP do anfitrião). Autenticação de máquina por
    token em `app/.env`; desligada sem `PRESENCE_INGEST_TOKEN` e fora do modo `ingest`."""
    s = get_settings()
    if (
        not s.presence_wifi_collection_enabled
        or s.presence_wifi_mode != "ingest"
        or not s.presence_ingest_token
    ):
        raise HTTPException(404, {"code": "not_found", "message": "Não encontrado"})
    if x_presence_token is None or not hmac.compare_digest(
        x_presence_token.encode(), s.presence_ingest_token.encode()
    ):
        raise HTTPException(401, {"code": "unauthorized", "message": "Não autenticado"})
    await service.observe(set(body.keys), Origin.real)
    return Response(status_code=204)


_probe = CameraProbe()


@router.get("/camera/status", dependencies=[Depends(require_operator)])
async def camera_status() -> CameraStatus:
    """Diagnóstico da câmara da porta: fonte, origem (real/simulada), vida e FPS. Sem imagem
    nem URL. Fonte em falha ou ausente: `camera_ok=false`, nunca «casa vazia»."""
    return _probe.status(
        video.fonte_atual(),
        resolve_kind(get_settings()),
        door_mask_configured=soleira_configurada() is not None,
    )
