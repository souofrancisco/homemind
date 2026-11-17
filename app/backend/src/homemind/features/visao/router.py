"""Arranca a thread de visão e liga-a ao motor (#28). Sem rotas: só `lifespan`.

Arranca depois de `engine` e `video` (ordem alfabética das features). Só liga com
`VIDEO_SOURCE` e `VISAO_DETETOR=modulo:Classe` (Detetor da P1, #4); sem eles o servidor
funciona na mesma (regras, `/api/simulate`, painel) e fica registado porquê.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from pydantic_settings import BaseSettings

from homemind.core.config import get_settings
from homemind.features.gestos.ponte import PublicadorFila
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.video import service as video
from homemind.features.visao.anotar import desenhar
from homemind.features.visao.thread import DetetorIndisponivel, ThreadVisao, carregar_detetor

log = logging.getLogger(__name__)


class VisaoSettings(BaseSettings):
    visao_detetor: str = ""  # ex.: homemind.features.visao.detetor:DetetorYolo


@asynccontextmanager
async def lifespan(app: FastAPI):
    especificacao = VisaoSettings().visao_detetor
    settings = get_settings()
    if not especificacao or not settings.video_source:
        log.warning("visão desligada: falta VISAO_DETETOR e/ou VIDEO_SOURCE")
        yield
        return
    try:
        detetor = carregar_detetor(especificacao)
    except DetetorIndisponivel as e:
        log.error("visão desligada: detetor indisponível (%s)", e)
        yield
        return
    engine = app.state.engine
    thread = ThreadVisao(
        video.get_fonte(),
        detetor,
        ProcessadorObjectOS.de_settings(settings),
        PublicadorFila(engine.loop, engine.fila),
    )
    thread.iniciar()

    def anotar(imagem, esqueleto=True):
        det = thread.ultima_deteccao()
        return imagem if det is None else desenhar(imagem, det, esqueleto=esqueleto)

    video.anotador = anotar
    log.info("visão ligada ao motor (%s)", especificacao)
    try:
        yield
    finally:
        video.anotador = None
        thread.parar()


router = APIRouter(lifespan=lifespan)
