"""Public catalogue commands and role-filtered views. No MCP external references."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from homemind.contracts.common import ContractModel, PowerW, ShortText, UtcDatetime
from homemind.contracts.devices import (
    ApplianceCategory,
    ApplianceOwnership,
    ApplianceScope,
    ApplianceStatus,
    DeviceKind,
    DeviceRole,
    DeviceSource,
)


class ApplianceCreate(ContractModel):
    name: ShortText
    category: ApplianceCategory
    scope: ApplianceScope
    home_room_id: UUID | None = None
    typical_watts: Annotated[PowerW, Field(gt=0)] | None = None


class AppliancePatch(ContractModel):
    # Fields not supplied are unchanged. Explicit null clears room/power/owner.
    name: ShortText | None = None
    category: ApplianceCategory | None = None
    scope: ApplianceScope | None = None
    owner_resident_id: UUID | None = None
    home_room_id: UUID | None = None
    typical_watts: Annotated[PowerW, Field(gt=0)] | None = None


class ApplianceView(ContractModel):
    id: UUID
    household_id: UUID
    name: str
    category: ApplianceCategory
    ownership: ApplianceOwnership
    typical_watts: float | None
    status: ApplianceStatus


class ApplianceDiagnosticView(ContractModel):
    """Operators see equipment metadata, not resident identities or ownership."""

    id: UUID
    household_id: UUID
    category: ApplianceCategory
    typical_watts: float | None
    status: ApplianceStatus


class ApplianceHistoryView(ContractModel):
    scope: ApplianceScope
    owner_resident_id: UUID | None
    home_room_id: UUID | None
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None


class DeviceCreateDemo(ContractModel):
    """Operator-provisioned demo/replay devices only; MCP discovery remains with P1."""

    name: ShortText
    room_id: UUID | None = None
    kind: DeviceKind
    role: DeviceRole = DeviceRole.none
    source: DeviceSource


class MeterAssignment(ContractModel):
    device_id: UUID | None


class MeterAssignmentView(ContractModel):
    appliance_id: UUID
    device_id: UUID | None
    effective_at: datetime
