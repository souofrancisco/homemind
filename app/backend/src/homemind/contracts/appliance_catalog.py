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
    DeviceView,
)
from homemind.contracts.energy import ConsumptionEvent


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
