"""Transactional automatic learning; no network, hardware or emitted events.

At most 64 active device buffers of 512 readings are retained, keyed by household too.
Closed sessions discard their buffer. The immutable event log supplies a bounded
recovery window on close (also after a restart/rollback); over 32768 readings or
missing opening evidence skips learning rather than learning from truncation.

ENERGY-04: every learned session is also recorded as a per-event sample
(`energy_signature_sample`, `origin_kind=learning`) and the signature is rebuilt from the
non-revoked samples (`store_signature`), which confirmations and revocations reuse.
"""

import json
import sqlite3
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import stable_id
from homemind.contracts.devices import ApplianceSignature, SignaturePattern
from homemind.contracts.domain_events import (
    DomainEvent,
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
    EnergyReadingRecorded,
    StoredEvent,
)
from homemind.contracts.energy import ConsumptionEvent, ConsumptionStatus, EnergyReading
from homemind.core.events import Handler
from homemind.features.energy.learning import (
    SessionObservation,
    SignatureBaseline,
    SignatureSample,
    assign_appliance,
    observation_time,
    observe_session,
    rebuild_signature,
    signature_id_for,
)
from homemind.features.energy.patterns import infer_pattern

INPUT_TYPES = [
    "energy.reading_recorded",
    "energy.consumption_detected",
    "energy.consumption_closed",
]
MAX_SESSION_READINGS = 32768


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def household_zone(conn: sqlite3.Connection, household_id: UUID) -> ZoneInfo | None:
    row = conn.execute("SELECT timezone FROM household WHERE id=?", (str(household_id),)).fetchone()
    return ZoneInfo(row["timezone"]) if row else None


def session_observation(
    conn: sqlite3.Connection, household_id: UUID, session: ConsumptionEvent
) -> SessionObservation | None:
    """Observation of a closed session from the committed immutable log (never memory)."""
    if session.ended_at is None:
        return None
    rows = conn.execute(
        "SELECT payload_json FROM domain_event WHERE household_id=?"
        " AND type='energy.reading_recorded' AND json_extract(payload_json,'$.device_id')=?"
        " AND julianday(COALESCE(json_extract(payload_json,'$.observed_at'),"
        " json_extract(payload_json,'$.ts'))) BETWEEN julianday(?) AND julianday(?)"
        " ORDER BY seq LIMIT ?",
        (
            str(household_id),
            str(session.device_id),
            session.started_at.isoformat(),
            session.ended_at.isoformat(),
            MAX_SESSION_READINGS + 1,
        ),
    ).fetchall()
    if len(rows) > MAX_SESSION_READINGS:
        return None
    readings = [EnergyReading.model_validate_json(row["payload_json"]) for row in rows]
    opening = [r for r in readings if r.usable and observation_time(r) == session.started_at]
    if not opening:
        return None
    first = max(opening, key=lambda r: (r.ts, str(r.id)))
    base_w = max(0.0, first.power_w - session.peak_w)
    return observe_session(session, readings, base_w)


def sample_of(obs: SessionObservation, hour_local: int) -> SignatureSample:
    pattern = infer_pattern(
        duration_s=obs.duration_s,
        cycles=obs.cycles,
        first_quarter_w=obs.first_quarter_w,
        last_quarter_w=obs.last_quarter_w,
    )
    return SignatureSample(obs.peak_w, obs.duration_s, pattern, hour_local)


@dataclass(frozen=True)
class NewSample:
    """Sample to append: `learning` (ENERGY-01) or `confirmation` (ENERGY-04, with request)."""

    source_event_id: UUID
    sample: SignatureSample
    origin_kind: str
    created_at: datetime
    identification_id: UUID | None = None


def active_samples(conn: sqlite3.Connection, signature_id: UUID) -> list[SignatureSample]:
    rows = conn.execute(
        "SELECT power_w,duration_s,pattern,hour_local FROM energy_signature_sample"
        " WHERE signature_id=? AND revoked_at IS NULL ORDER BY created_at,id",
        (str(signature_id),),
    )
    return [
        SignatureSample(
            r["power_w"], r["duration_s"], SignaturePattern(r["pattern"]), r["hour_local"]
        )
        for r in rows
    ]


def _baseline(conn: sqlite3.Connection, signature_id: UUID) -> SignatureBaseline | None:
    row = conn.execute(
        "SELECT * FROM energy_signature_baseline WHERE signature_id=?", (str(signature_id),)
    ).fetchone()
    if row is None:
        return None
    return SignatureBaseline(
        samples=row["samples"],
        watts_mean=row["watts_mean"],
        duration_typical_s=row["duration_typical_s"],
        typical_hours=tuple(json.loads(row["typical_hours_json"] or "[]")),
        pattern_counts={
            SignaturePattern(k): int(v) for k, v in json.loads(row["pattern_counts_json"]).items()
        },
    )


def store_signature(
    conn: sqlite3.Connection,
    catalog: ApplianceCatalog,
    household_id: UUID,
    appliance_id: UUID,
    new: list[NewSample],
    *,
    updated_at: datetime,
) -> ApplianceSignature | None:
    """Rebuild the signature from the non-revoked samples plus `new`, save it, then append `new`.

    Saving first lets the catalogue reject a retired appliance before any sample is written.
    Without samples (nor a pre-0401 baseline) the derived signature, its counts and its pattern
    lock are removed, so it no longer affects classification; readings, sessions and events are
    never touched.
    """
    sid = signature_id_for(appliance_id)
    lock = conn.execute(
        "SELECT pattern FROM energy_signature_lock WHERE signature_id=?", (str(sid),)
    ).fetchone()
    signature, counts = rebuild_signature(
        appliance_id,
        active_samples(conn, sid) + [n.sample for n in new],
        baseline=_baseline(conn, sid),
        locked=SignaturePattern(lock["pattern"]) if lock else None,
        updated_at=updated_at,
    )
    if signature is None:
        # Derived data owned by P1 (like the pattern PATCH): no sample, no signature.
        for table, column in (
            ("energy_signature_stats", "signature_id"),
            ("energy_signature_lock", "signature_id"),
            ("appliance_signature", "id"),
        ):
            conn.execute(f"DELETE FROM {table} WHERE {column}=?", (str(sid),))
    else:
        catalog.save_appliance_signature(conn, household_id, signature)
        conn.execute("DELETE FROM energy_signature_stats WHERE signature_id=?", (str(sid),))
        conn.executemany(
            "INSERT INTO energy_signature_stats(signature_id,pattern,count) VALUES (?,?,?)",
            [(str(sid), pattern.value, count) for pattern, count in counts.items()],
        )
    conn.executemany(
        "INSERT INTO energy_signature_sample(id,signature_id,appliance_id,source_event_id,"
        "power_w,duration_s,pattern,hour_local,origin_kind,identification_id,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(signature_id,source_event_id) DO NOTHING",
        [
            (
                str(stable_id("energy.signature_sample", str(sid), str(n.source_event_id))),
                str(sid),
                str(appliance_id),
                str(n.source_event_id),
                n.sample.power_w,
                n.sample.duration_s,
                n.sample.pattern.value,
                n.sample.hour_local,
                n.origin_kind,
                str(n.identification_id) if n.identification_id else None,
                stamp(n.created_at),
            )
            for n in new
        ],
    )
    return signature


def is_retired_error(exc: Exception) -> bool:
    # CatalogError belongs to HOUSE-03; do not import another feature.
    return getattr(exc, "status", None) == 409 and getattr(exc, "code", None) == "appliance_retired"


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
        obs = session_observation(conn, event.household_id, session)
        if obs is None:
            return []
        snapshots = catalog.appliances_for_household(conn, event.household_id, session.started_at)
        appliance_id = assign_appliance(obs, snapshots)
        if appliance_id is None:
            return []
        zone = household_zone(conn, event.household_id)
        if zone is None:
            return []
        sample = sample_of(obs, session.started_at.astimezone(zone).hour)
        try:
            store_signature(
                conn,
                catalog,
                event.household_id,
                appliance_id,
                [NewSample(event.id, sample, "learning", event.ts)],
                updated_at=obs.ended_at,
            )
        except Exception as exc:
            if is_retired_error(exc):
                return []
            raise
        return []

    return handle
