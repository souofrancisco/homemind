"""Assistente (ferramentas tipadas), ações propostas e automações. Dono: agent/automations (P3).

Distinções que os tipos impõem:
leitura (`AgentToolRequest/Result`) ≠ proposta (`ProposedAction`) ≠ confirmação humana
(`ActionConfirmation`) ≠ execução (`ActionExecutionResult`). O assistente nunca inventa
números: respostas geradas em código a partir de um `AgentToolResult` referenciado.
Ações físicas limitam-se ao que o MCP permite (lâmpada: power/brightness/color_rgb;
tomada: power) e dependem de flag + grant (connectors/write_grant). Esta camada não escreve.
"""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import (
    Cents,
    ContractModel,
    EnergyWh,
    OperationStatus,
    Period,
    PowerW,
    Provenance,
    ShortText,
    UtcDatetime,
    check_transition,
)

# --- conversa e ferramentas de leitura ---------------------------------------------------------


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"


class AgentMessage(ContractModel):
    id: UUID
    household_id: UUID
    role: MessageRole
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    ts: UtcDatetime


class AgentMessageIn(ContractModel):
    """Corpo de `POST /api/agent/messages`. O utilizador vem do token, nunca do corpo."""

    text: Annotated[str, Field(min_length=1, max_length=2000)]


class AgentTool(StrEnum):
    """Só leitura. Ações físicas passam por `ProposedAction`."""

    consumption_summary = "consumption_summary"
    budget_status = "budget_status"
    receipt = "receipt"
    top_appliances = "top_appliances"
    consumption_change = "consumption_change"
    explain_attribution = "explain_attribution"
    pending_confirmations = "pending_confirmations"


class AgentToolRequest(ContractModel):
    id: UUID
    tool: AgentTool
    period: Period | None = None
    bill_id: UUID | None = None

    @model_validator(mode="after")
    def _arguments(self) -> Self:
        needs_bill = self.tool is AgentTool.receipt
        needs_period = self.tool not in (AgentTool.receipt, AgentTool.pending_confirmations)
        if needs_bill != (self.bill_id is not None) or (needs_period and self.period is None):
            raise ValueError("argumentos incoerentes com a ferramenta")
        if not needs_period and self.period is not None:
            raise ValueError("argumentos incoerentes com a ferramenta")
        return self


class AgentToolResult(ContractModel):
    """A única fonte de números do assistente. `None` = sem dados (a resposta diz «não sei»)."""

    request_id: UUID
    tool: AgentTool
    status: OperationStatus
    provenance: Provenance | None = None
    energy_wh: EnergyWh | None = None
    cost_cents: Cents | None = None
    error_code: str | None = None
    appliances: list[ApplianceCost] = []
    previous_period: Period | None = None
    previous_cost_cents: Cents | None = None
    difference_cents: Annotated[int, Field(strict=True, ge=-(10**12), le=10**12)] | None = None
    attribution_parts: list[AttributionPart] = []
    final: bool | None = None
    pending_count: Annotated[int, Field(strict=True, ge=0)] | None = None
    pending: list[PendingConfirmation] = []

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        ok = self.status is OperationStatus.succeeded
        if ok and self.error_code is not None:
            raise ValueError("sucesso sem error_code")
        if not ok and (self.energy_wh is not None or self.cost_cents is not None):
            raise ValueError("falha sem valores")
        if (self.energy_wh is not None or self.cost_cents is not None) and not self.provenance:
            raise ValueError("valores exigem proveniência")
        return self


class ApplianceCost(ContractModel):
    label: ShortText
    cost_cents: Cents
    percent: Annotated[int, Field(strict=True, ge=0, le=100)]
    provenance: Provenance


class AttributionPart(ContractModel):
    label: ShortText
    amount_cents: Cents
    provenance: Provenance


class PendingConfirmation(ContractModel):
    appliance_name: ShortText | None = None
    estimated_cost_cents: Cents | None = None
    expires_at: UtcDatetime
    provenance: Provenance


# --- ações físicas ---------------------------------------------------------------------------


class DeviceCapability(StrEnum):
    power = "power"
    brightness = "brightness"
    color_rgb = "color_rgb"


class RgbColor(ContractModel):
    r: Annotated[int, Field(strict=True, ge=0, le=255)]
    g: Annotated[int, Field(strict=True, ge=0, le=255)]
    b: Annotated[int, Field(strict=True, ge=0, le=255)]


class DeviceCommand(ContractModel):
    """Um comando num dispositivo. `target_device_id` é interno; o MCP resolve-se no conector."""

    target_device_id: UUID
    capability: DeviceCapability
    power: bool | None = None
    brightness: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None
    color_rgb: RgbColor | None = None

    @model_validator(mode="after")
    def _one_value(self) -> Self:
        values = {
            DeviceCapability.power: self.power,
            DeviceCapability.brightness: self.brightness,
            DeviceCapability.color_rgb: self.color_rgb,
        }
        if values[self.capability] is None or sum(v is not None for v in values.values()) != 1:
            raise ValueError("exatamente o valor da capacidade indicada")
        return self


class ActionStatus(StrEnum):
    proposed = "proposed"
    confirmed = "confirmed"
    rejected = "rejected"
    expired = "expired"
    executed = "executed"  # há um ActionExecutionResult (qualquer desfecho)


ACTION_TRANSITIONS = {
    ActionStatus.proposed: frozenset(
        {ActionStatus.confirmed, ActionStatus.rejected, ActionStatus.expired}
    ),
    ActionStatus.confirmed: frozenset({ActionStatus.executed, ActionStatus.expired}),
    ActionStatus.rejected: frozenset(),
    ActionStatus.expired: frozenset(),
    ActionStatus.executed: frozenset(),
}


class ProposedAction(ContractModel):
    id: UUID
    household_id: UUID
    proposed_for_resident_id: UUID  # quem tem de confirmar
    command: DeviceCommand
    rationale: Annotated[str, Field(min_length=1, max_length=300)]
    requires_confirmation: Literal[True] = True  # nunca executa sem confirmação humana
    status: ActionStatus = ActionStatus.proposed
    proposed_at: UtcDatetime
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def _expiry(self) -> Self:
        if self.expires_at <= self.proposed_at:
            raise ValueError("expires_at tem de ser posterior à proposta")
        return self

    def transition(self, new: ActionStatus) -> None:
        check_transition(ACTION_TRANSITIONS, self.status, new)


class ActionConfirmation(ContractModel):
    action_id: UUID
    resident_id: UUID
    accepted: bool
    at: UtcDatetime


class ExecutionStatus(StrEnum):
    confirmed = "confirmed"  # releitura confirmou o novo estado
    failed = "failed"  # erro claro, nada aplicado
    uncertain = "uncertain"  # `isError=false` sem releitura confirmativa; NUNCA repetir
    blocked = "blocked"  # guardas (flag/grant/whitelist) impediram a escrita


class ActionExecutionResult(ContractModel):
    action_id: UUID
    status: ExecutionStatus
    mcp_is_error: bool | None = None  # None: a chamada nem chegou a ser feita
    readback_confirmed: bool = False
    executed_at: UtcDatetime
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")] | None = None

    @model_validator(mode="after")
    def _honest(self) -> Self:
        if self.status is ExecutionStatus.confirmed and not self.readback_confirmed:
            raise ValueError("`isError=false` não prova nada: confirmar exige releitura")
        if self.status is not ExecutionStatus.confirmed and self.readback_confirmed:
            raise ValueError("releitura confirmada contradiz o estado")
        if self.status is ExecutionStatus.blocked and self.mcp_is_error is not None:
            raise ValueError("bloqueada: não houve chamada ao MCP")
        if self.status is not ExecutionStatus.confirmed and self.code is None:
            raise ValueError("falha, incerteza ou bloqueio exige code")
        return self

    @property
    def may_retry(self) -> bool:
        """Uma escrita de resultado incerto nunca se repete: só se relê."""
        return self.status in (ExecutionStatus.failed, ExecutionStatus.blocked)


class AgentResponse(ContractModel):
    id: UUID
    household_id: UUID
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    tool_result_ids: list[UUID] = []  # request_id dos resultados que sustentam os números
    tool_results: list[AgentToolResult] = []  # dados tipados que sustentam a resposta deste turno
    proposed_actions: list[ProposedAction] = []
    created_at: UtcDatetime
    interpreter: Literal["llm", "rules"] | None = None


# --- automações ------------------------------------------------------------------------------


class AutomationSource(StrEnum):
    natural_language = "natural_language"
    manual = "manual"
    suggested = "suggested"


class AutomationStatus(StrEnum):
    draft = "draft"
    proposed = "proposed"
    active = "active"
    disabled = "disabled"


AUTOMATION_TRANSITIONS = {
    AutomationStatus.draft: frozenset({AutomationStatus.proposed}),
    AutomationStatus.proposed: frozenset({AutomationStatus.active, AutomationStatus.draft}),
    AutomationStatus.active: frozenset({AutomationStatus.disabled}),
    AutomationStatus.disabled: frozenset({AutomationStatus.active}),
}


class TriggerKind(StrEnum):
    power_above = "power_above"  # potência de um dispositivo acima de X W durante Y s
    presence_changed = "presence_changed"


class AutomationTrigger(ContractModel):
    kind: TriggerKind
    device_id: UUID | None = None
    threshold_w: Annotated[PowerW, Field(gt=0)] | None = None
    duration_s: Annotated[int, Field(strict=True, ge=0, le=86_400)] | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.kind is TriggerKind.power_above:
            if self.device_id is None or self.threshold_w is None or self.duration_s is None:
                raise ValueError("power_above exige device_id, threshold_w e duration_s")
        elif any(v is not None for v in (self.device_id, self.threshold_w, self.duration_s)):
            raise ValueError("presence_changed não tem parâmetros")
        return self


class AutomationRule(ContractModel):
    id: UUID
    household_id: UUID
    name: ShortText
    source: AutomationSource
    nl_text: Annotated[str, Field(max_length=500)] | None = None
    trigger: AutomationTrigger
    actions: Annotated[list[DeviceCommand], Field(min_length=1, max_length=5)]
    requires_confirmation: Literal[True] = True  # todas as ações são físicas
    status: AutomationStatus = AutomationStatus.draft
    created_by_resident_id: UUID
    approved_by_resident_id: UUID | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.status is AutomationStatus.active and self.approved_by_resident_id is None:
            raise ValueError("regra ativa exige aprovação explícita")
        if self.source is AutomationSource.natural_language and not self.nl_text:
            raise ValueError("origem em linguagem natural exige nl_text")
        if any(
            a.capability is not DeviceCapability.power or a.power is not False for a in self.actions
        ):
            raise ValueError("a única ação de uma regra é desligar a tomada")
        return self

    def transition(self, new: AutomationStatus) -> None:
        check_transition(AUTOMATION_TRANSITIONS, self.status, new)


# --- votação das regras da casa (SAFE-04, D-35 PROPOSTA) ----------------------------------------


class AutomationVote(ContractModel):
    """Voto de um morador numa regra `proposed`. A regra e a casa vêm do contexto; o morador
    vem sempre do token."""

    resident_id: UUID
    approve: bool
    at: UtcDatetime


class RuleVerdict(StrEnum):
    approved = "approved"  # maioria absoluta a favor: a regra passa a `active`
    rejected = "rejected"  # maioria impossível ou prazo sem maioria: `proposed -> draft`
    pending = "pending"


class RuleApprovalOutcome(ContractModel):
    verdict: RuleVerdict
    votes_for: Annotated[int, Field(strict=True, ge=0)]
    votes_against: Annotated[int, Field(strict=True, ge=0)]
    majority: Annotated[int, Field(strict=True, ge=1)]  # votos a favor necessários

    @property
    def decided(self) -> bool:
        return self.verdict is not RuleVerdict.pending


def absolute_majority(eligible: int) -> int:
    """Mais de metade dos elegíveis (2 → 2, 3 → 2, 4 → 3, 5 → 3). Não confundir com
    `votes_needed` (D-32), que é «pelo menos metade»."""
    return eligible // 2 + 1


def rule_approval_outcome(
    votes: Collection[AutomationVote], eligible: Collection[UUID], *, expired: bool = False
) -> RuleApprovalOutcome:
    """Fonte única da votação de regras. Aprovada quando os votos a favor atingem a maioria
    absoluta; rejeitada quando já não a pode atingir ou quando o prazo acabou sem maioria.
    Votos repetidos ou de quem não é elegível são erro (o serviço já os impede)."""
    voters = [v.resident_id for v in votes]
    if not eligible or len(set(eligible)) != len(eligible):
        raise ValueError("elegíveis em falta ou repetidos")
    if len(set(voters)) != len(voters) or not set(voters) <= set(eligible):
        raise ValueError("votos repetidos ou de quem não é elegível")
    majority = absolute_majority(len(eligible))
    pro = sum(v.approve for v in votes)
    against = len(voters) - pro
    if pro >= majority:
        verdict = RuleVerdict.approved
    elif expired or against >= len(eligible) - majority + 1:
        verdict = RuleVerdict.rejected
    else:
        verdict = RuleVerdict.pending
    return RuleApprovalOutcome(
        verdict=verdict, votes_for=pro, votes_against=against, majority=majority
    )
