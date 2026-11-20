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

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self, get_args
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from homemind.contracts.agent import (
    ActionExecutionResult,
    AutomationRule,
    AutomationStatus,
    ProposedAction,
    RuleVerdict,
)
from homemind.contracts.billing import (
    Attribution,
    BudgetThreshold,
    Contestation,
    RuleProposal,
)
from homemind.contracts.common import (
    ContractModel,
    EnergyWh,
    PowerW,
    Provenance,
    UtcDatetime,
    new_id,
)
from homemind.contracts.energy import (
    ApplianceIdentificationRequest,
    ConsumptionEvent,
    ConsumptionStatus,
    EnergyReading,
    PowerStep,
)
from homemind.contracts.notification import (
    ConfirmationOutcome,
    ConfirmationRequest,
    NotificationKind,
    NotificationRef,
    NotificationResponse,
    NotificationScope,
    NotificationSeverity,
)
from homemind.contracts.presence import (
    DoorCrossed,
    HouseOccupancy,
    PersonPresence,
    PresenceConfirmationRequest,
    PresenceEvent,
    PresenceSourceRevoked,
)
from homemind.contracts.safety import AwayState, SafetyAlert, SecurityAction, SecurityPanelState
from homemind.contracts.sensors import SensorReading


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
    """Um por resposta aceite. Em `confirmation_request` sai um por VOTO, com `outcome`:
    billing só atribui quando `outcome.decided` (D-32); sem decisão até `expires_at`, billing
    divide por todos pelo seu próprio prazo (não há evento de expiração)."""

    response: NotificationResponse
    ref: NotificationRef | None = None  # o que foi respondido (ex.: o consumo)
    outcome: ConfirmationOutcome | None = None  # só em `confirmation_request`


class AlertKind(StrEnum):
    peak = "peak"
    anomaly = "anomaly"  # gasto do dia muito acima do habitual (ALERT-03)
    forgotten_appliance = "forgotten_appliance"
    mismatch = "mismatch"


class AlertRaisedData(ContractModel):
    """Campos de contexto opcionais (compatível com v1): o aviso só diz o que foi medido.

    `peak` (ALERT-03): `device_id`, `power_w` (última potência acima do limite) e `since`
    (início do episódio; a duração é `ts - since`); `room_id` só se a tomada estiver numa
    zona comum registada (`None` = «pico de consumo por identificar»); `appliance_id` só com
    identificação confiante de um aparelho comum (nunca pessoal: o nome identificaria o dono).

    `anomaly` (ALERT-03): `device_id` e `room_id` (sempre zona comum), `day` (data local),
    `energy_wh` (gasto do dia até agora) e `baseline_wh` (o habitual: mediana dos dias
    anteriores com leituras suficientes).
    """

    kind: AlertKind
    severity: NotificationSeverity
    ref: NotificationRef | None = None
    resident_id: UUID | None = None  # alertas pessoais
    device_id: UUID | None = None
    room_id: UUID | None = None
    appliance_id: UUID | None = None
    power_w: PowerW | None = None
    since: UtcDatetime | None = None
    day: date | None = None
    energy_wh: EnergyWh | None = None
    baseline_wh: EnergyWh | None = None


class ColdRoomData(ContractModel):
    """ALERT-06: o quarto do morador esteve várias noites abaixo do limiar (média da noite,
    só leituras `ok` do sensor de clima). Aviso PRIVADO ao morador; o senhorio nunca o vê."""

    resident_id: UUID
    room_id: UUID
    cold_nights: Annotated[int, Field(strict=True, ge=1)]
    window_nights: Annotated[int, Field(strict=True, ge=1)]
    threshold_c: float
    coldest_night_c: float  # média da noite mais fria da janela
    last_night: date  # data (local) do início da última noite contada
    # Plafond solidário (BILL-03) que o quarto ainda tem no mês de `last_night`, já descontado o
    # aquecimento provado coberto até agora. `None`: o quarto não tem plafond.
    allowance_left_wh: EnergyWh | None = None


class AutomationExecutedData(ContractModel):
    rule_id: UUID
    result: ActionExecutionResult


class AutomationVoteDecidedData(ContractModel):
    """A votação de uma regra fechou (SAFE-04): só o veredicto e as contagens, nunca quem votou
    o quê. `rejected` com `expired=False` = maioria impossível; com `expired=True` = prazo."""

    rule_id: UUID
    verdict: Literal[RuleVerdict.approved, RuleVerdict.rejected]
    votes_for: Annotated[int, Field(strict=True, ge=0)]
    votes_against: Annotated[int, Field(strict=True, ge=0)]
    eligible: Annotated[int, Field(strict=True, ge=1)]
    expired: bool = False


class AutomationStatusChangedData(ContractModel):
    """Mudança de estado de uma regra depois de proposta (ex.: `active -> disabled` quando um
    morador a suspende). `resident_id` é quem agiu; `None` = o sistema (ex.: prazo)."""

    rule_id: UUID
    from_status: AutomationStatus
    to_status: AutomationStatus
    resident_id: UUID | None = None

    @model_validator(mode="after")
    def _changed(self) -> Self:
        if self.from_status is self.to_status:
            raise ValueError("o estado tem de mudar")
        return self


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


class EnergyIdentificationNeeded(EventBase):
    """«O que é este aparelho?» (ENERGY-04): P3 transforma-o numa notificação da casa."""

    type: Literal["energy.identification_needed"] = "energy.identification_needed"
    data: ApplianceIdentificationRequest


# --- presença -------------------------------------------------------------------------------


class PresenceDoorCrossed(EventBase):
    type: Literal["presence.door_crossed"] = "presence.door_crossed"
    data: DoorCrossed


class PresenceChanged(EventBase):
    type: Literal["presence.changed"] = "presence.changed"
    data: PersonPresence


class PresenceCueRecorded(EventBase):
    """Pista por pessoa (Wi-Fi, manual, aparelho), auditável. Só presence a consome."""

    type: Literal["presence.cue_recorded"] = "presence.cue_recorded"
    data: PresenceEvent


class PresenceConfirmationNeeded(EventBase):
    type: Literal["presence.confirmation_needed"] = "presence.confirmation_needed"
    data: PresenceConfirmationRequest


class PresenceSourceRevokedEvent(EventBase):
    """O morador desligou uma fonte de presença (PRIV-03 #51). Só metadados (quem e que fonte):
    quem tem cópias derivadas (faturação) descarta-as. Imutável, como um registo."""

    type: Literal["presence.source_revoked"] = "presence.source_revoked"
    data: PresenceSourceRevoked


class PresenceOccupancyChanged(EventBase):
    type: Literal["presence.occupancy_changed"] = "presence.occupancy_changed"
    data: HouseOccupancy


# --- sensores e segurança -------------------------------------------------------------------


class SensorReadingRecorded(EventBase):
    type: Literal["sensor.reading_recorded"] = "sensor.reading_recorded"
    data: SensorReading


class SafetyAlertRaised(EventBase):
    """Também para a resolução: o mesmo `data.id` com `status=resolved`."""

    type: Literal["safety.alert_raised"] = "safety.alert_raised"
    data: SafetyAlert


class SafetyAwayChanged(EventBase):
    """Só quando o estado AWAY muda (SAFE-02, PROPOSTA, SIMULADO). Sem rotas nem pessoas."""

    type: Literal["safety.away_changed"] = "safety.away_changed"
    data: AwayState


class SafetySecurityChanged(EventBase):
    """Leitura do painel de segurança SIMULADO (SAFE-02, PROPOSTA). Sem pessoas."""

    type: Literal["safety.security_changed"] = "safety.security_changed"
    data: SecurityPanelState


class SafetySecurityAction(EventBase):
    """Proposta de armar/desarmar SIMULADA e as suas decisões: o mesmo `data.id` em
    `proposed` e depois `confirmed`/`cancelled` (SAFE-02, PROPOSTA). Nunca execução física."""

    type: Literal["safety.security_action"] = "safety.security_action"
    data: SecurityAction


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


class BillingContestationChanged(EventBase):
    """Contestação aberta ou decidida (BILL-06): `data.status` diz qual."""

    type: Literal["billing.contestation_changed"] = "billing.contestation_changed"
    data: Contestation


class BillingRulesProposalChanged(EventBase):
    """Proposta de mudança da regra da sala (HOUSE-04): aberta, aprovada pela maioria, rejeitada,
    retirada, substituída ou caducada (`data.status`). Só contagens de votos."""

    type: Literal["billing.rules_proposal_changed"] = "billing.rules_proposal_changed"
    data: RuleProposal


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


class AlertsColdRoom(EventBase):
    type: Literal["alerts.cold_room"] = "alerts.cold_room"
    data: ColdRoomData


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


class AutomationVoteDecided(EventBase):
    type: Literal["automation.vote_decided"] = "automation.vote_decided"
    data: AutomationVoteDecidedData


class AutomationStatusChanged(EventBase):
    type: Literal["automation.status_changed"] = "automation.status_changed"
    data: AutomationStatusChangedData


DomainEvent = Annotated[
    EnergyReadingRecorded
    | EnergyStepDetected
    | EnergyConsumptionDetected
    | EnergyConsumptionClosed
    | EnergyIdentificationNeeded
    | PresenceDoorCrossed
    | PresenceChanged
    | PresenceCueRecorded
    | PresenceConfirmationNeeded
    | PresenceOccupancyChanged
    | PresenceSourceRevokedEvent
    | SensorReadingRecorded
    | SafetyAlertRaised
    | SafetyAwayChanged
    | SafetySecurityChanged
    | SafetySecurityAction
    | BillingConfirmationNeeded
    | BillingAttributionChanged
    | BillingBillCreated
    | BillingBillFinalized
    | BillingAllocationPublished
    | BillingContestationChanged
    | BillingRulesProposalChanged
    | NotificationCreated
    | NotificationResponded
    | AlertsThresholdCrossed
    | AlertsAlertRaised
    | AlertsColdRoom
    | AgentActionProposed
    | AutomationProposed
    | AutomationExecuted
    | AutomationVoteDecided
    | AutomationStatusChanged,
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
