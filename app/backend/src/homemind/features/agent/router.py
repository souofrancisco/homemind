"""Assistente na app: `POST /api/households/{household_id}/agent/messages` (AGENT-01/02, parcial).

IMPLEMENTADO: ferramentas de leitura, resposta validada, recurso determinístico sem LLM.
PLANEADO: providers reais (P4/P1), histórico, ações propostas (AGENT-03), automações (AGENT-04).
Os dados de hoje são SIMULADOS (`simulated.py`) e só existem na casa de demonstração.
Sem lifespan, sem tabelas, sem eventos.
"""

import logging
from functools import lru_cache
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from homemind.contracts import fixtures as fx
from homemind.contracts.agent import AgentMessageIn, AgentResponse
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.features.agent.assistant import Assistant
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.llm import Complete, LLMUnavailable, nvidia_complete
from homemind.features.agent.providers import BudgetProvider, ConsumptionProvider, ReceiptProvider
from homemind.features.agent.simulated import EmptyProviders, SimulatedProviders
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

_EMPTY = EmptyProviders()


@lru_cache
def _simulated() -> SimulatedProviders:
    return SimulatedProviders()


def _providers(
    household_id: UUID, source_kind: str
) -> tuple[ConsumptionProvider, BudgetProvider, ReceiptProvider]:
    """Dados simulados só para a casa de demonstração; as outras não têm dados (D8)."""
    demo = household_id == fx.HOUSEHOLD and source_kind == "demo"
    p = _simulated() if demo else _EMPTY
    return p, p, p


@router.post("/households/{household_id}/agent/messages")
async def send_message(
    body: AgentMessageIn,
    access: AgentAccess,
    db: DbDep,
    clock: ClockDep,
    complete: CompleteDep,
) -> AgentResponse:
    """Pergunta do morador ao assistente. O residente e o papel vêm do token, nunca do corpo."""
    now = clock()
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind, timezone FROM household WHERE id = ?", (str(access.household_id),)
        ).fetchone()
    )
    consumption, budget, receipt = _providers(access.household_id, row["source_kind"])
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
