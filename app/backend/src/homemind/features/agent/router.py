"""Assistente na app: `POST /api/households/{household_id}/agent/messages` (AGENT-01/02, parcial).

IMPLEMENTADO: ferramentas de leitura, resposta validada, recurso determinístico sem LLM.
PLANEADO: providers reais (P4/P1), histórico, ações propostas (AGENT-03), automações (AGENT-04).
Os dados de hoje são SIMULADOS (`simulated.py`) e só existem na casa de demonstração.
Sem lifespan, sem tabelas, sem eventos.
"""

import logging
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from homemind.contracts.agent import AgentMessageIn, AgentResponse
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.features.agent.actions_router import StateDep, reply_to_action_request
from homemind.features.agent.actions_router import router as actions_router
from homemind.features.agent.assistant import Assistant
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.guardrails import is_action_request
from homemind.features.agent.llm import Complete, LLMUnavailable, nvidia_complete
from homemind.features.agent.providers import (
    BudgetProvider,
    ConsumptionProvider,
    ProviderSet,
    ReceiptProvider,
)
from homemind.features.agent.sources import RegisteredDep, resolve
from homemind.features.agent.tools import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agent"])

# Senhorio e operador: 403 (matriz `PERMISSIONS[agent]`, só inquilinos).
AgentAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.agent, Operation.write))]


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
) -> tuple[ConsumptionProvider, BudgetProvider, ReceiptProvider]:
    """Real registado primeiro; SIMULADO só na casa de demonstração; senão sem dados (D8)."""
    return resolve(registered, household_id, source_kind)


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
    """Pergunta do morador ao assistente. O residente e o papel vêm do token, nunca do corpo."""
    now = clock()
    if is_action_request(body.text):
        # AGENT-03: um pedido de ação nunca chega ao LLM nem executa nada; só gera uma proposta
        # a confirmar (ou uma recusa). Ver `actions_router.py`.
        return await reply_to_action_request(state, db, access, body.text, now)
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind, timezone FROM household WHERE id = ?", (str(access.household_id),)
        ).fetchone()
    )
    consumption, budget, receipt = _providers(registered, access.household_id, row["source_kind"])
    ctx = ToolContext(
        household_id=access.household_id,
        resident_id=access.resident_id,
        role=access.role,
        now=now,
        period=now.astimezone(ZoneInfo(row["timezone"])).strftime("%Y-%m"),
    )
    settings = get_agent_settings()
    assistant = Assistant(
        ToolRegistry(consumption, budget, receipt),
        complete,
        max_steps=settings.agent_max_steps,
        timeout_s=settings.agent_llm_timeout_s,
        total_timeout_s=settings.agent_total_timeout_s,
    )
    reply = await assistant.reply(body.text, ctx)
    return AgentResponse(
        id=uuid4(),
        household_id=access.household_id,
        text=reply.text,
        tool_result_ids=list(reply.tool_result_ids),
        proposed_actions=[],
        created_at=now,
    )


# AGENT-03: listar, ver, confirmar e rejeitar ações propostas.
router.include_router(actions_router)
