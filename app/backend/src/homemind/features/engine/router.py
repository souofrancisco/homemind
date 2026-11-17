"""API do motor (docs/contratos.md): estado, histórico, regras, NVIDIA, off e WebSocket.

REST protegido por login (Bearer). O WebSocket autentica-se na primeira mensagem
`{"type": "auth", "token": "<access token>"}` — nunca token no URL (ficaria nos logs).
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials

from homemind.connectors.fake_home import FakeHome
from homemind.connectors.mcp_home import McpHome
from homemind.contracts.eventos import Evento
from homemind.contracts.home import Home
from homemind.contracts.regras import Rule
from homemind.features.auth.service import CurrentUser, current_user
from homemind.features.engine.config import EngineSettings, get_engine_settings
from homemind.features.engine.engine import (
    Engine,
    ErrorData,
    ErrorMessage,
    HomeState,
    HomeStateMessage,
    OffResult,
    Tempos,
)
from homemind.features.engine.eventlog import EventLog
from homemind.features.engine.llm import (
    LLMIndisponivel,
    PedidoNaoSuportado,
    PropostaInvalida,
    cliente_nvidia,
    propor_regra,
)
from homemind.features.engine.rules import RulesStore, descrever
from homemind.features.engine.schemas import (
    EventList,
    ParseRequest,
    ParseResponse,
    RuleList,
    RulePatch,
    Status,
)
from homemind.features.video import service as video


def criar_home(s: EngineSettings) -> Home:
    if s.home_backend == "mcp":
        return McpHome()
    return FakeHome()


def criar_engine(s: EngineSettings) -> Engine:
    regras = RulesStore(s.rules_path)
    regras.carregar()
    tempos = Tempos(
        espera_s=s.espera,
        aviso_s=s.aviso_s,
        brilho_aviso=s.brilho_aviso,
        suspenso_max_s=s.suspenso_max_s,
        tarifa_eur_kwh=s.tarifa_eur_kwh,
    )
    return Engine(criar_home(s), regras, EventLog(s.events_path, s.home_backend), tempos)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = criar_engine(get_engine_settings())
    iniciar_home = getattr(engine.home, "iniciar", None)
    if iniciar_home is not None:
        await iniciar_home()
    tarefas: list[asyncio.Task] = []
    try:
        await engine.iniciar()
        app.state.engine = engine  # a visão publica com engine.publicar_de_thread(evento)
        tarefas = [
            asyncio.create_task(engine.consumir()),
            asyncio.create_task(engine.vigiar_camara(video.camara_ok)),  # sinal de vida da P1
        ]
        yield
    finally:
        for t in tarefas:
            t.cancel()
        await asyncio.gather(*tarefas, return_exceptions=True)
        await engine.parar()
        parar_home = getattr(engine.home, "parar", None)
        if parar_home is not None:
            await parar_home()


router = APIRouter(prefix="/api", tags=["engine"], lifespan=lifespan)


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


EngineDep = Annotated[Engine, Depends(get_engine)]


def _erro(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message})


@router.get("/status")
def obter_saude(_: CurrentUser, engine: EngineDep) -> Status:
    """Só saúde das integrações. O estado completo está em `GET /api/state` e no WS."""
    s = engine.home_state()
    return Status(
        camera_ok=s.camera_ok, mcp_ok=s.mcp_ok, backend=s.backend, updated_at=s.updated_at
    )


@router.get("/state")
def obter_estado(_: CurrentUser, engine: EngineDep) -> HomeState:
    """O mesmo `HomeState` do WS, para carregar a página ou quando o WS está em baixo."""
    return engine.home_state()


@router.get("/events")
def historico(
    _: CurrentUser, engine: EngineDep, limit: Annotated[int, Query(ge=1, le=50)] = 50
) -> EventList:
    """Últimas linhas do registo (mais antigas primeiro). As novas chegam pelo WS (`event`)."""
    return EventList(events=engine.registo.recentes(limit))


@router.post("/off")
async def desligar_tudo(_: CurrentUser, engine: EngineDep) -> OffResult:
    """Sempre 200: `success` diz se ambos os dispositivos ficaram confirmadamente desligados."""
    return await engine.desligar_tudo()


@router.post("/simulate")
async def simular_evento(evento: Evento, _: CurrentUser, engine: EngineDep) -> HomeState:
    """Injeta um evento SIMULADO (desenvolvimento/plano B). Fica marcado `[SIMULADO]` no registo."""
    if get_engine_settings().home_backend != "fake":
        raise _erro(403, "simulation_disabled", "Simulação só com HOME_BACKEND=fake")
    await engine.processar(evento, simulado=True)
    return engine.home_state()


@router.get("/rules")
def listar_regras(_: CurrentUser, engine: EngineDep) -> RuleList:
    return RuleList(rules=engine.regras.listar())


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def guardar_regra(regra: Rule, _: CurrentUser, engine: EngineDep) -> Rule:
    """Cria ou substitui (mesmo id). `enabled` → desativa as outras regras do mesmo objeto."""
    engine.regras.guardar(regra)
    engine.registo.registar(f"Regra guardada: {descrever(regra)}")
    await engine.notificar()
    return regra


@router.patch("/rules/{rule_id}")
async def ativar_regra(rule_id: str, corpo: RulePatch, _: CurrentUser, engine: EngineDep) -> Rule:
    regra = engine.regras.definir_ativa(rule_id, corpo.enabled)
    if regra is None:
        raise _erro(404, "rule_not_found", "Regra não encontrada")
    engine.registo.registar(f"Regra «{regra.nome}» {'ativada' if corpo.enabled else 'desativada'}")
    await engine.notificar()
    return regra


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def apagar_regra(rule_id: str, _: CurrentUser, engine: EngineDep) -> None:
    if not engine.regras.apagar(rule_id):
        raise _erro(404, "rule_not_found", "Regra não encontrada")
    engine.registo.registar(f"Regra apagada: {rule_id}")
    await engine.notificar()


@router.post("/rules/parse")
async def propor(pedido: ParseRequest, _: CurrentUser, engine: EngineDep) -> ParseResponse:
    """Texto → proposta (NVIDIA). Não grava nem executa nada."""
    try:
        regra = await propor_regra(pedido.text, cliente_nvidia(get_engine_settings()))
    except LLMIndisponivel as e:
        raise _erro(503, "nvidia_unavailable", str(e)) from None
    except PedidoNaoSuportado as e:
        raise _erro(400, "rule_not_supported", f"Pedido não suportado: {e}") from None
    except PropostaInvalida as e:
        raise _erro(502, "invalid_proposal", str(e)) from None
    # Nunca sobrescrever uma regra existente por acidente.
    base, n = regra.id, 2
    while engine.regras.obter(regra.id):
        regra.id = f"{base[:37]}-{n}"
        n += 1
    atual = engine.regras.ativa_para(regra.objeto)
    return ParseResponse(
        proposal=regra,
        summary=descrever(regra),
        replaces=atual.nome if atual and regra.enabled else None,
    )


async def _autenticar(websocket: WebSocket) -> bool:
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        if not isinstance(msg, dict) or msg.get("type") != "auth":
            return False
        cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=str(msg.get("token", "")))
        await asyncio.to_thread(current_user, cred)
        return True
    except (TimeoutError, ValueError, HTTPException, WebSocketDisconnect):
        return False


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    """1.º `{"type":"auth","token":…}`; depois `home_state` imediato, e `home_state`/`event`."""
    await websocket.accept()
    if not await _autenticar(websocket):
        erro = ErrorMessage(data=ErrorData(code="unauthorized", message="Não autenticado"))
        try:
            await websocket.send_text(erro.model_dump_json())
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:  # cliente já saiu
            pass
        return
    engine: Engine = websocket.app.state.engine
    fila = engine.subscrever()

    async def enviar() -> None:
        await websocket.send_text(HomeStateMessage(data=engine.home_state()).model_dump_json())
        while True:
            await websocket.send_text((await fila.get()).model_dump_json())

    async def receber() -> None:  # deteta a desconexão; mensagens do cliente são ignoradas
        while True:
            await websocket.receive_text()

    tarefas = [asyncio.create_task(enviar()), asyncio.create_task(receber())]
    try:
        _, pendentes = await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
        for t in pendentes:
            t.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        engine.cancelar_subscricao(fila)
        for t in tarefas:
            if t.done() and not t.cancelled():
                t.exception()  # já tratada (desconexão); evita aviso de exceção não lida
