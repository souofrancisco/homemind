"""Deterministic session observations and incremental appliance signatures.

ENERGY-04: the signature is rebuilt from the non-revoked per-event samples
(`rebuild_signature`), plus a fixed baseline for signatures learned before 0401.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from homemind.contracts.appliance_catalog import ApplianceSnapshot
from homemind.contracts.common import stable_id
from homemind.contracts.devices import ApplianceSignature, SignatureOrigin, SignaturePattern
from homemind.contracts.energy import ConsumptionEvent, EnergyReading
from homemind.features.energy.patterns import infer_pattern


@dataclass(frozen=True)
class SessionObservation:
    device_id: UUID
    started_at: datetime
    ended_at: datetime
    peak_w: float
    duration_s: float
    cycles: int
    first_quarter_w: float
    last_quarter_w: float
    # Filled only after unambiguous assignment; learn needs an ID for a first signature.
    appliance_id: UUID | None = None


def observation_time(reading: EnergyReading) -> datetime:
    return reading.observed_at if reading.observed_at is not None else reading.ts


def observe_session(
    event: ConsumptionEvent, readings: list[EnergyReading], base_w: float
) -> SessionObservation | None:
    if event.ended_at is None or event.ended_at <= event.started_at:
        return None
    # Equal observation timestamps: latest poll wins, then stable UUID tie-break.
    usable = sorted(
        (
            r
            for r in readings
            if r.device_id == event.device_id
            and r.usable
            and event.started_at <= observation_time(r) <= event.ended_at
        ),
        key=lambda r: (observation_time(r), r.ts, str(r.id)),
    )
    points = {observation_time(r): max(0.0, r.power_w - base_w) for r in usable}
    if not points:
        return None
    ordered = sorted(points.items())
    intervals: list[tuple[float, float]] = []
    cycles, fell, was_on = 0, False, False
    for i, (at, watts) in enumerate(ordered):
        if watts < 50 and was_on:
            fell = True
        elif watts >= 50 and abs(watts - event.peak_w) <= 50:
            if fell:
                cycles += 1
            fell, was_on = False, True
        end = ordered[i + 1][0] if i + 1 < len(ordered) else event.ended_at
        seconds = (end - at).total_seconds()
        if watts >= 50 and seconds > 0:
            intervals.append((seconds, watts))
    on_time = sum(seconds for seconds, _ in intervals)
    if on_time <= 0:
        return None

    def average(start: float, end: float) -> float:
        elapsed, total = 0.0, 0.0
        for seconds, watts in intervals:
            overlap = max(0.0, min(end, elapsed + seconds) - max(start, elapsed))
            total += overlap * watts
            elapsed += seconds
        return total / (end - start)

    return SessionObservation(
        device_id=event.device_id,
        started_at=event.started_at,
        ended_at=event.ended_at,
        peak_w=event.peak_w,
        duration_s=(event.ended_at - event.started_at).total_seconds(),
        cycles=cycles,
        first_quarter_w=average(0, on_time / 4),
        last_quarter_w=average(on_time * 3 / 4, on_time),
    )


def assign_appliance(obs: SessionObservation, snapshots: list[ApplianceSnapshot]) -> UUID | None:
    linked = {s.appliance_id for s in snapshots if s.meter_device_id == obs.device_id}
    if len(linked) == 1:
        return next(iter(linked))
    powered = {
        s.appliance_id
        for s in snapshots
        if s.typical_watts is not None
        and abs(obs.peak_w - s.typical_watts) <= max(50.0, s.typical_watts * 0.1)
    }
    return next(iter(powered)) if len(powered) == 1 else None


def learn(
    existing: ApplianceSignature | None,
    obs: SessionObservation,
    *,
    pattern_counts: dict[SignaturePattern, int],
    locked: SignaturePattern | None,
    hour_local: int,
) -> tuple[ApplianceSignature, dict[SignaturePattern, int]]:
    appliance_id = existing.appliance_id if existing else obs.appliance_id
    if appliance_id is None or obs.peak_w <= 50 or obs.duration_s <= 0:
        raise ValueError("learning requires an assigned appliance, power >50 W and duration >0")
    if obs.appliance_id is not None and obs.appliance_id != appliance_id:
        raise ValueError("observation belongs to a different appliance")
    pattern = infer_pattern(
        duration_s=obs.duration_s,
        cycles=obs.cycles,
        first_quarter_w=obs.first_quarter_w,
        last_quarter_w=obs.last_quarter_w,
    )
    counts = dict(pattern_counts)
    counts[pattern] = counts.get(pattern, 0) + 1
    # Stable lexical tie-break, independent of event/dict insertion order.
    dominant = min(counts, key=lambda p: (-counts[p], p.value))
    n = existing.samples if existing else 0
    mean = ((existing.watts_mean * n if existing else 0) + obs.peak_w) / (n + 1)
    duration = (((existing.duration_typical_s or 0) * n if existing else 0) + obs.duration_s) / (
        n + 1
    )
    return ApplianceSignature(
        id=stable_id("energy.signature", str(appliance_id)),
        appliance_id=appliance_id,
        watts_mean=mean,
        watts_tolerance=max(50.0, mean * 0.1),
        duration_typical_s=max(1, round(duration)),
        pattern=locked or dominant,
        typical_hours=sorted(
            set((existing.typical_hours or []) if existing else []) | {hour_local}
        ),
        samples=n + 1,
        origin=SignatureOrigin.learned,
        updated_at=obs.ended_at,
    ), counts


def signature_id_for(appliance_id: UUID) -> UUID:
    """One learned signature per appliance (ENERGY-01)."""
    return stable_id("energy.signature", str(appliance_id))


@dataclass(frozen=True)
class SignatureSample:
    """One non-revoked per-event sample (ENERGY-04): power above base, duration, pattern, hour."""

    power_w: float
    duration_s: float
    pattern: SignaturePattern
    hour_local: int


@dataclass(frozen=True)
class SignatureBaseline:
    """Aggregate learned before per-event samples existed (migration 0401); never revocable."""

    samples: int
    watts_mean: float
    duration_typical_s: int | None
    typical_hours: tuple[int, ...] = ()
    pattern_counts: dict[SignaturePattern, int] = field(default_factory=dict)


def rebuild_signature(
    appliance_id: UUID,
    samples: list[SignatureSample],
    *,
    baseline: SignatureBaseline | None = None,
    locked: SignaturePattern | None = None,
    updated_at: datetime,
) -> tuple[ApplianceSignature | None, dict[SignaturePattern, int]]:
    """Signature from the current samples (same rules as `learn`): mean power and duration,
    tolerance max(50 W, 10 %), most frequent pattern (lexical tie-break) unless locked, and the
    union of local start hours. No samples and no baseline: no signature (`None`)."""
    n0 = baseline.samples if baseline else 0
    n = n0 + len(samples)
    counts: dict[SignaturePattern, int] = dict(baseline.pattern_counts) if baseline else {}
    for s in samples:
        counts[s.pattern] = counts.get(s.pattern, 0) + 1
    if n == 0:
        return None, {}
    mean = ((baseline.watts_mean * n0 if baseline else 0) + sum(s.power_w for s in samples)) / n
    if mean <= 50:
        raise ValueError("a signature requires a mean power above 50 W")
    duration = (
        ((baseline.duration_typical_s or 0) * n0 if baseline else 0)
        + sum(s.duration_s for s in samples)
    ) / n
    dominant = min(counts, key=lambda p: (-counts[p], p.value))
    hours = set(baseline.typical_hours if baseline else ()) | {s.hour_local for s in samples}
    return ApplianceSignature(
        id=signature_id_for(appliance_id),
        appliance_id=appliance_id,
        watts_mean=mean,
        watts_tolerance=max(50.0, mean * 0.1),
        duration_typical_s=max(1, round(duration)),
        pattern=locked or dominant,
        typical_hours=sorted(hours),
        samples=n,
        origin=SignatureOrigin.learned,
        updated_at=updated_at,
    ), counts
