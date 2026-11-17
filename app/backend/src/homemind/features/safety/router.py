"""Arranca o consumidor de segurança no barramento. Sem rotas (API de alertas: APP-02/P3)."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from homemind.features.safety.service import SafetyService

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sem resolvedor de aquecedores (ENERGY-03 pendente): só as regras de fumo ficam ativas.
    service = SafetyService()
    service.attach(app.state.bus)
    app.state.safety = service
    log.info("safety: consumidor subscrito (janela+aquecedor aguarda ENERGY-03)")
    yield


router = APIRouter(lifespan=lifespan)
