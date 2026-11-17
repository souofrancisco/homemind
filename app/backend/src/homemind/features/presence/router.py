"""Presença (P2). IMPLEMENTADO: telemóveis com opt-in e pistas Wi-Fi (PRES-03).

Todas as rotas levam `?household_id=` e exigem inquilino com membership ativa: o senhorio e o
operador recebem `403 forbidden_role`, quem não é membro `404 household_not_found`. A identidade
vem sempre da sessão, nunca do pedido. A rota de observações do varrimento no anfitrião é a única
sem utilizador (token de máquina) e não entra no contrato OpenAPI.
"""

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import Field

from homemind.contracts.common import ContractModel, Origin, ShortText
from homemind.contracts.presence import PersonPresence, PresenceDeviceView
from homemind.core.access import (
    HouseholdAccess,
    Operation,
    Resource,
    get_clock,
    require_access,
)
from homemind.core.config import get_settings
from homemind.core.events import EventBus
from homemind.features.presence.fusion import FusionParams
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


async def _ticker(service: PresenceService, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await service.tick()
        except Exception as e:  # noqa: BLE001 - o ciclo não pode morrer
            log.error("reavaliação de presença falhou (%s)", type(e).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    }
    status, message = table.get(e.code, (400, "Pedido inválido"))
    return HTTPException(status, {"code": e.code, "message": message})


@router.get("")
async def get_presence(access: Read, service: Service) -> PersonPresence:
    """O meu estado. Ninguém mais o vê (nem colegas, nem senhorio, nem operador)."""
    return await service.own_state(access.household_id, access.resident_id)


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
