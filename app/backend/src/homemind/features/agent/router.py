"""Assistente na app: `POST` e `GET /api/households/{household_id}/agent/messages` (AGENT-01/02).

IMPLEMENTADO: ferramentas de leitura, resposta validada, recurso determinístico sem LLM; histórico
da conversa por residente (`GET`, #111; cada troca é gravada pelo `POST`, retenção curta, P-25).
AGENT-03b: um alerta de janela aberta com aquecimento gera propostas a confirmar
(`safety_consumer.py`, subscrito no `lifespan`). PLANEADO: providers reais (P4/P1), automações
(AGENT-04). Ações propostas: `actions_router.py`.
Os dados de hoje são SIMULADOS (`simulated.py`) e só existem na casa de demonstração.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Query

from homemind.contracts.agent import AgentMessage, AgentMessageIn, AgentResponse
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    get_clock,
    require_access,
)
from homemind.features.agent import history
from homemind.features.agent.actions_router import StateDep, reply_to_action_request
from homemind.features.agent.actions_router import router as actions_router
from homemind.features.agent.assistant import Assistant
from homemind.features.agent.budget_light_consumer import (
    BUDGET_LIGHT_CONSUMER,
    BUDGET_LIGHT_EVENT_TYPES,
)
from homemind.features.agent.budget_light_consumer import make_handler as make_budget_handler
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.guardrails import is_action_request
from homemind.features.agent.llm import Complete, LLMUnavailable, nvidia_complete
from homemind.features.agent.providers import (
    ApplianceProvider,
    BudgetProvider,
    ConsumptionProvider,
    ProviderSet,
    ReceiptProvider,
)
from homemind.features.agent.safety_consumer import (
    SAFETY_CONSUMER,
    SAFETY_EVENT_TYPES,
)
from homemind.features.agent.safety_consumer import make_handler as make_safety_handler
from homemind.features.agent.sources import RegisteredDep, resolve
from homemind.features.agent.tools import ToolContext, ToolRegistry

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # AGENT-03b: alertas de janela aberta -> propostas a confirmar. O relógio é o das rotas (o
    # override de `get_clock` nos testes também vale aqui). O consumidor só propõe; nunca executa.
    clock = app.dependency_overrides.get(get_clock, get_clock)()
    app.state.bus.subscribe(SAFETY_CONSUMER, make_safety_handler(app, clock), SAFETY_EVENT_TYPES)
    # ALERT-06: orçamento a 80/100 % -> proposta de pôr a lâmpada âmbar/vermelha (só propõe).
    app.state.bus.subscribe(
        BUDGET_LIGHT_CONSUMER, make_budget_handler(app, clock), BUDGET_LIGHT_EVENT_TYPES
    )
    yield


router = APIRouter(prefix="/api", tags=["agent"], lifespan=lifespan)

# Senhorio e operador: 403 (matriz `PERMISSIONS[agent]`, só inquilinos).
AgentAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.agent, Operation.write))]
ReadAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.agent, Operation.read))]


def get_complete() -> Complete | None:
    """Cliente do LLM, ou `None` (assistente sem LLM, recurso determinístico). Só há LLM com
    `AGENT_LLM_ENABLED` ligado (P-06 pendente) e chave configurada. Os testes substituem-no."""
    settings = get_agent_settings()
    if not settings.agent_llm_enabled or not settings.nvidia_api_key:
        return None
    try:
        return nvidia_complete(settings)
    except LLMUnavailable:
        return None


CompleteDep = Annotated[Complete | None, Depends(get_complete)]


def _providers(
    registered: ProviderSet, household_id: UUID, source_kind: str
) -> tuple[ConsumptionProvider, BudgetProvider, ReceiptProvider, ApplianceProvider]:
    """Real registado primeiro; SIMULADO só na casa de demonstração; senão sem dados (D8)."""
    return resolve(registered, household_id, source_kind)


async def _remember(db, access: HouseholdAccess, user_text: str, reply_text: str, now) -> None:
    settings = get_agent_settings()
    await db.run(
        lambda c: history.record_exchange(
            c,
            access.household_id,
            access.resident_id,
            user_text,
            reply_text,
            now,
            settings.agent_history_keep,
            settings.agent_history_days,
        )
    )


@router.post("/households/{household_id}/agent/messages")
async def send_message(
    body: AgentMessageIn,
    access: AgentAccess,
    db: DbDep,
    clock: ClockDep,
    state: StateDep,
    complete: CompleteDep,
    registered: RegisteredDep,
) -> AgentResponse:
    """Pergunta do morador ao assistente. O residente e o papel vêm do token, nunca do corpo.
    A troca (pergunta e resposta) fica gravada no histórico do próprio, com retenção curta."""
    now = clock()
    if is_action_request(body.text):
        # AGENT-03: um pedido de ação nunca chega ao LLM nem executa nada; só gera uma proposta
        # a confirmar (ou uma recusa). Ver `actions_router.py`.
        response = await reply_to_action_request(state, db, access, body.text, now)
        await _remember(db, access, body.text, response.text, now)
        return response
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind, timezone FROM household WHERE id = ?", (str(access.household_id),)
        ).fetchone()
    )
    consumption, budget, receipt, appliances = _providers(
        registered, access.household_id, row["source_kind"]
    )
    ctx = ToolContext(
        household_id=access.household_id,
        resident_id=access.resident_id,
        role=access.role,
        now=now,
        period=now.astimezone(ZoneInfo(row["timezone"])).strftime("%Y-%m"),
    )
    settings = get_agent_settings()
    if settings.agent_llm_scope == "demo" and row["source_kind"] != "demo":
        complete = None
    assistant = Assistant(
        ToolRegistry(
            consumption,
            budget,
            receipt,
            appliances,
            registered.attribution,
            registered.confirmations,
        ),
        complete,
        max_steps=settings.agent_max_steps,
        timeout_s=settings.agent_llm_timeout_s,
        total_timeout_s=settings.agent_total_timeout_s,
    )
    # O histórico NUNCA é passado ao assistente nem ao LLM (P-06): cada pergunta é independente.
    reply = await assistant.reply(body.text, ctx)
    await _remember(db, access, body.text, reply.text, now)
    return AgentResponse(
        id=uuid4(),
        household_id=access.household_id,
        text=reply.text,
        tool_result_ids=list(reply.tool_result_ids),
        tool_results=list(reply.tool_results),
        proposed_actions=[],
        created_at=now,
        interpreter="llm" if reply.used_llm else "rules",
    )


@router.get("/households/{household_id}/agent/messages")
async def list_messages(
    access: ReadAccess, db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[AgentMessage]:
    """Histórico do PRÓPRIO residente (nunca o de outro), do mais antigo para o mais recente.
    Só para a app o mostrar: não volta a entrar no assistente."""
    return await db.run(
        lambda c: history.list_messages(c, access.household_id, access.resident_id, limit)
    )


# AGENT-03: listar, ver, confirmar e rejeitar ações propostas.
router.include_router(actions_router)
