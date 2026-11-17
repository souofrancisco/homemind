from datetime import datetime

from pydantic import BaseModel, Field

from homemind.contracts.home import Backend
from homemind.contracts.regras import Rule
from homemind.features.engine.eventlog import EventLogItem


class Status(BaseModel):
    camera_ok: bool
    mcp_ok: bool
    backend: Backend
    updated_at: datetime


class RuleList(BaseModel):
    rules: list[Rule]


class RulePatch(BaseModel):
    enabled: bool


class ParseRequest(BaseModel):
    text: str = Field(min_length=3, max_length=300, examples=["Quando pego no livro, luz verde"])


class ParseResponse(BaseModel):
    """Só proposta: não é gravada nem executada. Gravar com `POST /api/rules` após confirmação."""

    proposal: Rule
    summary: str
    replaces: str | None = Field(
        None, description="Nome da regra ativa do mesmo objeto que será desativada ao gravar"
    )


class EventList(BaseModel):
    events: list[EventLogItem]
