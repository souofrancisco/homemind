"""Contrato público da API: erros e o conjunto de modelos partilhados exposto no OpenAPI.

`OPENAPI_MODELS` é o que `make contracts` entrega ao frontend além dos modelos das rotas
reais (ver `core/openapi_models.py`). Só entram DTOs e contratos públicos. Ficam de fora de
propósito: `Device` (tem `external_ref`), `Resident` (tem `sub`), `Membership` (tem o
`presence_opt_in` de terceiros), `ApplianceSignature`, `PresenceEvent`, `ConfirmationRequest`
(lista de quem pode responder: payload interno P4→P3), `PresenceDevice` (tem `match_key`),
`PresenceConfirmationRequest`, `SensorReading`, `SafetyAlert` (chegam como `NotificationView`)
e os eventos de domínio (`StoredEvent`
inclui presença de pessoas). Chegam à app como DTOs filtrados por papel.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from homemind.contracts import agent, billing, devices, energy, household, notification, presence
from homemind.contracts.common import ContractModel, Provenance


class ErrorCode(StrEnum):
    """Códigos públicos em `{"error": {"code", "message"}}` (os de HTTP genérico são `http_<n>`)."""

    invalid_request = "invalid_request"
    forbidden_role = "forbidden_role"
    household_not_found = "household_not_found"
    bill_not_found = "bill_not_found"
    notification_not_found = "notification_not_found"
    already_responded = "already_responded"
    notification_expired = "notification_expired"
    bill_finalized = "bill_finalized"
    bill_inconsistent = "bill_inconsistent"
    simulation_disabled = "simulation_disabled"
    internal_error = "internal_error"


class ApiError(ContractModel):
    code: str
    message: str


class ApiErrorBody(ContractModel):
    error: ApiError


OPENAPI_MODELS: tuple[type[BaseModel], ...] = (
    ApiErrorBody,
    Provenance,
    # households
    household.HouseholdView,
    household.RoomView,
    household.ResidentView,
    household.MemberView,
    household.MembershipSelfView,
    household.MeContext,
    # dispositivos e energia
    devices.DeviceView,
    devices.Appliance,
    energy.EnergyReading,
    energy.ConsumptionEvent,
    energy.EnergySummary,
    # presença (só moradores com opt-in e o próprio; nunca o senhorio)
    presence.PersonPresence,
    presence.PresenceMeIn,
    presence.HouseOccupancy,
    presence.PresenceDeviceView,
    presence.CameraStatus,
    # faturação
    billing.Attribution,
    billing.ElectricityBill,
    billing.BillAllocation,
    billing.LandlordBillView,
    billing.Budget,
    billing.Contestation,
    # notificações
    notification.NotificationView,
    notification.NotificationPreferences,
    # assistente e automações
    agent.AgentMessageIn,
    agent.AgentResponse,
    agent.AgentToolResult,
    agent.ProposedAction,
    agent.ActionConfirmation,
    agent.ActionExecutionResult,
    agent.AutomationRule,
)
