"""Shared P1/P4 port for the temporal appliance catalogue.

Feature modules depend on this contract, never on ``features.appliances``. The
connection is supplied by the caller so catalogue reads/writes participate in
the caller's existing SQLite transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from homemind.contracts.devices import (
    ApplianceOwnership,
    ApplianceSignature,
    Device,
    DeviceRole,
    DeviceView,
)
from homemind.contracts.energy import ConsumptionEvent
from homemind.contracts.household import RoomKind


@dataclass(frozen=True)
class DeviceLocation:
    role: DeviceRole
    room_id: UUID | None
    room_kind: RoomKind | None


@dataclass(frozen=True)
class ApplianceSnapshot:
    appliance_id: UUID
    ownership: ApplianceOwnership
    typical_watts: float | None
    meter_device_id: UUID | None


@dataclass(frozen=True)
class MeterContextSegment:
    """Configured meter for one half-open portion of a requested period."""

    started_at: datetime
    ended_at: datetime
    device_id: UUID | None


@dataclass(frozen=True)
class ApplianceContextSegment:
    """Historical appliance ownership for one half-open portion of an event."""

    started_at: datetime
    ended_at: datetime | None
    ownership: ApplianceOwnership | None


@runtime_checkable
class ApplianceCatalog(Protocol):
    """Transaction-scoped P1/P4 access to HOUSE-03-owned catalogue data."""

    def device_location(
        self, conn: sqlite3.Connection, household_id: UUID, device_id: UUID
    ) -> DeviceLocation | None: ...

    def appliances_for_household(
        self, conn: sqlite3.Connection, household_id: UUID, at: datetime
    ) -> list[ApplianceSnapshot]: ...

    def register_device(self, conn: sqlite3.Connection, device: Device) -> DeviceView: ...

    def save_appliance_signature(
        self, conn: sqlite3.Connection, household_id: UUID, signature: ApplianceSignature
    ) -> None: ...

    def signatures_for_household(
        self, conn: sqlite3.Connection, household_id: UUID
    ) -> dict[UUID, list[ApplianceSignature]]: ...

    def meter_at(
        self, conn: sqlite3.Connection, household_id: UUID, appliance_id: UUID, at: datetime
    ) -> UUID | None: ...

    def meters_for_period(
        self,
        conn: sqlite3.Connection,
        household_id: UUID,
        appliance_id: UUID,
        started_at: datetime,
        ended_at: datetime,
    ) -> list[MeterContextSegment]: ...

    def ownership_at(
        self, conn: sqlite3.Connection, household_id: UUID, appliance_id: UUID, at: datetime
    ) -> ApplianceOwnership | None: ...

    def context_segments_for_consumption(
        self, conn: sqlite3.Connection, event: ConsumptionEvent
    ) -> list[ApplianceContextSegment]: ...

    def context_for_consumption(
        self, conn: sqlite3.Connection, event: ConsumptionEvent
    ) -> ApplianceOwnership | None: ...

    def create_learned_appliance(
        self,
        conn: sqlite3.Connection,
        household_id: UUID,
        *,
        name: str,
        typical_watts: float,
        ownership: ApplianceOwnership,
        registered_by_resident_id: UUID,
        at: datetime,
    ) -> UUID:
        """ENERGY-04: regista um aparelho (categoria `other`) a partir de «O que é este
        aparelho?», com as mesmas validações do registo pela API: quem regista é inquilino
        ativo, um aparelho pessoal é de quem regista e um comum não tem dono. Se o nome já
        existir para quem regista, acrescenta « (2)», « (3)»… Erros: `CatalogError` (403/422)."""
        ...
