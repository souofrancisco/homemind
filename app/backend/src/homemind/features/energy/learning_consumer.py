"""Transactional automatic learning; no network, hardware or emitted events.

At most 64 active device buffers of 512 readings are retained, keyed by household too.
Closed sessions discard their buffer. The immutable event log supplies a bounded
recovery window on close (also after a restart/rollback); over 32768 readings or
missing opening evidence skips learning rather than learning from truncation.
"""

import sqlite3
from collections import OrderedDict, deque
from dataclasses import replace
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import stable_id
from homemind.contracts.devices import SignaturePattern
from homemind.contracts.domain_events import (
    DomainEvent,
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
    EnergyReadingRecorded,
    StoredEvent,
)
from homemind.contracts.energy import ConsumptionStatus, EnergyReading
from homemind.core.events import Handler
from homemind.features.energy.learning import (
    assign_appliance,
    learn,
    observation_time,
    observe_session,
)

INPUT_TYPES = [
    "energy.reading_recorded",
    "energy.consumption_detected",
    "energy.consumption_closed",
]
MAX_SESSION_READINGS = 32768


def make_learning_consumer(catalog: ApplianceCatalog) -> Handler:
    buffers: OrderedDict[tuple[UUID, UUID], deque[EnergyReading]] = OrderedDict()

    def handle(conn: sqlite3.Connection, stored: StoredEvent) -> list[DomainEvent]:
        event = stored.event
        if isinstance(event, EnergyReadingRecorded):
            key = (event.household_id, event.data.device_id)
            if key not in buffers:
                return []
            buffers[key].append(event.data)
            buffers.move_to_end(key)
            return []
        if isinstance(event, EnergyConsumptionDetected):
            key = (event.household_id, event.data.device_id)
            buffers.setdefault(key, deque(maxlen=512))
            if len(buffers) > 64:
                buffers.popitem(last=False)
            return []
        if not isinstance(event, EnergyConsumptionClosed):
            return []
        session = event.data
        buffers.pop((event.household_id, session.device_id), None)
        if session.status is not ConsumptionStatus.closed or session.peak_w <= 50:
            return []
        # Use the committed immutable log, not mutated memory, on every retry.
        rows = conn.execute(
            "SELECT payload_json FROM domain_event WHERE household_id=?"
            " AND type='energy.reading_recorded' AND json_extract(payload_json,'$.device_id')=?"
            " AND julianday(COALESCE(json_extract(payload_json,'$.observed_at'),"
            " json_extract(payload_json,'$.ts'))) BETWEEN julianday(?) AND julianday(?)"
            " ORDER BY seq LIMIT ?",
            (
                str(event.household_id),
                str(session.device_id),
                session.started_at.isoformat(),
                session.ended_at.isoformat(),
                MAX_SESSION_READINGS + 1,
            ),
        ).fetchall()
        if len(rows) > MAX_SESSION_READINGS:
            return []
        readings = [EnergyReading.model_validate_json(row["payload_json"]) for row in rows]
        opening = [r for r in readings if r.usable and observation_time(r) == session.started_at]
        if not opening:
            return []
        first = max(opening, key=lambda r: (r.ts, str(r.id)))
        base_w = max(0.0, first.power_w - session.peak_w)
        obs = observe_session(session, readings, base_w)
        if obs is None:
            return []
        snapshots = catalog.appliances_for_household(conn, event.household_id, session.started_at)
        appliance_id = assign_appliance(obs, snapshots)
        if appliance_id is None:
            return []
        sid = stable_id("energy.signature", str(appliance_id))
        signatures = catalog.signatures_for_household(conn, event.household_id)
        existing = next((s for s in signatures.get(appliance_id, []) if s.id == sid), None)
        counts = {
            SignaturePattern(r["pattern"]): r["count"]
            for r in conn.execute(
                "SELECT pattern,count FROM energy_signature_stats WHERE signature_id=?", (str(sid),)
            )
        }
        lock = conn.execute(
            "SELECT pattern FROM energy_signature_lock WHERE signature_id=?", (str(sid),)
        ).fetchone()
        house = conn.execute(
            "SELECT timezone FROM household WHERE id=?", (str(event.household_id),)
        ).fetchone()
        if house is None:
            return []
        signature, counts = learn(
            existing,
            replace(obs, appliance_id=appliance_id),
            pattern_counts=counts,
            locked=SignaturePattern(lock["pattern"]) if lock else None,
            hour_local=session.started_at.astimezone(ZoneInfo(house["timezone"])).hour,
        )
        try:
            catalog.save_appliance_signature(conn, event.household_id, signature)
        except Exception as exc:
            # CatalogError belongs to HOUSE-03; do not import another feature.
            if (
                getattr(exc, "status", None) == 409
                and getattr(exc, "code", None) == "appliance_retired"
            ):
                return []
            raise
        conn.executemany(
            "INSERT INTO energy_signature_stats(signature_id,pattern,count) VALUES (?,?,?)"
            " ON CONFLICT(signature_id,pattern) DO UPDATE SET count=excluded.count",
            [(str(sid), pattern.value, count) for pattern, count in counts.items()],
        )
        return []

    return handle
