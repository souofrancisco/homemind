"""Eventos de domínio: envelope versionado + um payload tipado por evento.

Semântica (ver docs/architecture/event-flow.md):
- Imutáveis. O produtor NÃO define `seq`: atribui-o a persistência (`StoredEvent`).
- `id` estável (idempotência do produtor e dos consumidores); `correlation_id` agrupa um fluxo
  e não ordena nada; a ordem é `seq`.
- `provenance` do evento = origem e natureza do que descreve; tem de coincidir com a do payload.
- Sem imagens, frames, tokens nem ids externos (MCP) em nenhum payload: os modelos têm
  `extra=forbid` e só usam ids internos.
- `schema_version`: mudanças compatíveis (campo opcional novo) mantêm a versão; mudanças
  incompatíveis criam uma nova classe/versão e um *upcast* antes de entregar a consumidores.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self, get_args
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from homemind.contracts.agent import ActionExecutionResult, AutomationRule, ProposedAction
from homemind.contracts.billing import Attribution, BudgetThreshold
from homemind.contracts.common import (
    ContractModel,
    Provenance,
    UtcDatetime,
    new_id,
)
from homemind.contracts.energy import (
    ConsumptionEvent,
    ConsumptionStatus,
    EnergyReading,
    PowerStep,
)
from homemind.contracts.notification import (
    ConfirmationRequest,
    NotificationKind,
    NotificationRef,
    NotificationResponse,
    NotificationScope,
    NotificationSeverity,
)
from homemind.contracts.presence import DoorCrossed, PersonPresence


class EventBase(ContractModel):
    id: UUID = Field(default_factory=new_id)
    schema_version: Literal[1] = 1
    ts: UtcDatetime
    household_id: UUID
    correlation_id: UUID = Field(default_factory=new_id)
    provenance: Provenance

    @model_validator(mode="after")
    def _payload_matches_envelope(self) -> Self:
        data = getattr(self, "data", None)
        prov = getattr(data, "provenance", None)
        if isinstance(prov, Provenance) and prov != self.provenance:
            raise ValueError("a proveniência do evento difere da do payload")
        hid = getattr(data, "household_id", None)
        if hid is not None and hid != self.household_id:
            raise ValueError("o payload é de outra casa")
        return self


# --- payloads sem modelo próprio -----------------------------------------------------------


class BillRef(ContractModel):
    bill_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)] = 1


class AllocationPublished(ContractModel):
    bill_id: UUID
    allocation_id: UUID
    resident_id: UUID


class NotificationCreatedData(ContractModel):
    notification_id: UUID
    scope: NotificationScope
    kind: NotificationKind
    recipient_resident_id: UUID | None = None


class NotificationRespondedData(ContractModel):
    response: NotificationResponse
    ref: NotificationRef | None = None  # o que foi respondido (ex.: o consumo)


class AlertKind(StrEnum):
    peak = "peak"
    forgotten_appliance = "forgotten_appliance"
    mismatch = "mismatch"


class AlertRaisedData(ContractModel):
    kind: AlertKind
    severity: NotificationSeverity
    ref: NotificationRef | None = None
    resident_id: UUID | None = None  # alertas pessoais


class AutomationExecutedData(ContractModel):
    rule_id: UUID
    result: ActionExecutionResult


# --- energia --------------------------------------------------------------------------------


class EnergyReadingRecorded(EventBase):
    type: Literal["energy.reading_recorded"] = "energy.reading_recorded"
    data: EnergyReading


class EnergyStepDetected(EventBase):
    type: Literal["energy.step_detected"] = "energy.step_detected"
    data: PowerStep


class EnergyConsumptionDetected(EventBase):
    type: Literal["energy.consumption_detected"] = "energy.consumption_detected"
    data: ConsumptionEvent

    @model_validator(mode="after")
    def _ongoing(self) -> Self:
        if self.data.status is not ConsumptionStatus.ongoing:
            raise ValueError("`consumption_detected` descreve um consumo a decorrer")
        return self


class EnergyConsumptionClosed(EventBase):
    type: Literal["energy.consumption_closed"] = "energy.consumption_closed"
    data: ConsumptionEvent

    @model_validator(mode="after")
    def _finished(self) -> Self:
        if self.data.status is ConsumptionStatus.ongoing:
            raise ValueError("`consumption_closed` descreve um consumo terminado")
        return self


# --- presença -------------------------------------------------------------------------------


class PresenceDoorCrossed(EventBase):
    type: Literal["presence.door_crossed"] = "presence.door_crossed"
    data: DoorCrossed


class PresenceChanged(EventBase):
    type: Literal["presence.changed"] = "presence.changed"
    data: PersonPresence


# --- faturação ------------------------------------------------------------------------------


class BillingConfirmationNeeded(EventBase):
    type: Literal["billing.confirmation_needed"] = "billing.confirmation_needed"
    data: ConfirmationRequest


class BillingAttributionChanged(EventBase):
    type: Literal["billing.attribution_changed"] = "billing.attribution_changed"
    data: Attribution


class BillingBillCreated(EventBase):
    type: Literal["billing.bill_created"] = "billing.bill_created"
    data: BillRef


class BillingBillFinalized(EventBase):
    type: Literal["billing.bill_finalized"] = "billing.bill_finalized"
    data: BillRef


class BillingAllocationPublished(EventBase):
    type: Literal["billing.allocation_published"] = "billing.allocation_published"
    data: AllocationPublished


# --- notificações e alertas ------------------------------------------------------------------


class NotificationCreated(EventBase):
    type: Literal["notification.created"] = "notification.created"
    data: NotificationCreatedData


class NotificationResponded(EventBase):
    type: Literal["notification.responded"] = "notification.responded"
    data: NotificationRespondedData


class AlertsThresholdCrossed(EventBase):
    type: Literal["alerts.threshold_crossed"] = "alerts.threshold_crossed"
    data: BudgetThreshold


class AlertsAlertRaised(EventBase):
    type: Literal["alerts.alert_raised"] = "alerts.alert_raised"
    data: AlertRaisedData


# --- agente e automações --------------------------------------------------------------------


class AgentActionProposed(EventBase):
    type: Literal["agent.action_proposed"] = "agent.action_proposed"
    data: ProposedAction


class AutomationProposed(EventBase):
    type: Literal["automation.proposed"] = "automation.proposed"
    data: AutomationRule


class AutomationExecuted(EventBase):
    type: Literal["automation.executed"] = "automation.executed"
    data: AutomationExecutedData


DomainEvent = Annotated[
    EnergyReadingRecorded
    | EnergyStepDetected
    | EnergyConsumptionDetected
    | EnergyConsumptionClosed
    | PresenceDoorCrossed
    | PresenceChanged
    | BillingConfirmationNeeded
    | BillingAttributionChanged
    | BillingBillCreated
    | BillingBillFinalized
    | BillingAllocationPublished
    | NotificationCreated
    | NotificationResponded
    | AlertsThresholdCrossed
    | AlertsAlertRaised
    | AgentActionProposed
    | AutomationProposed
    | AutomationExecuted,
    Field(discriminator="type"),
]

domain_event_adapter: TypeAdapter[DomainEvent] = TypeAdapter(DomainEvent)

# type -> classe; a persistência valida `type` aqui antes de aceitar um evento.
EVENT_TYPES: dict[str, type[EventBase]] = {
    get_args(cls.model_fields["type"].annotation)[0]: cls
    for cls in get_args(get_args(DomainEvent)[0])
}


class StoredEvent(ContractModel):
    """Evento já persistido: `seq` é global, crescente e atribuído pela base de dados."""

    seq: Annotated[int, Field(strict=True, ge=1)]
    event: DomainEvent
