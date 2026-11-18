"""Pure, timestamp-driven detection of independent loads on each socket.

Steps compare consecutive usable readings, including changes below the threshold.
With one active session, sample-and-hold energy uses measured socket power above
the pre-load baseline, clamped to zero. With overlapping active sessions, each
integrates its opening delta instead; fluctuations do not redistribute their power.
A gap breaks step comparison and integration. On recovery, loads that no longer
fit the baseline plus their opening deltas close at the last pre-gap OK reading,
without a PowerStep or any energy attributed to the gap. Loads that fit stay open.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from uuid import UUID

from homemind.contracts.common import EnergyWh, Provenance, stable_id
from homemind.contracts.devices import ApplianceOwnership, ApplianceScope
from homemind.contracts.domain_events import (
    DomainEvent,
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
    EnergyStepDetected,
)
from homemind.contracts.energy import (
    ApplianceMatch,
    ConsumptionEvent,
    ConsumptionStatus,
    EnergyReading,
    LocationKind,
    PowerStep,
)
from homemind.features.energy.classifier import SessionFeatures
from homemind.features.energy.patterns import infer_pattern


def reading_time(reading: EnergyReading) -> datetime:
    return reading.observed_at if reading.observed_at is not None else reading.ts


@dataclass
class _Session:
    id: UUID
    started_at: datetime
    watts: float
    provenance: Provenance
    location: LocationKind = LocationKind.unknown
    room_id: UUID | None = None
    watt_seconds: Decimal = Decimal(0)
    stopped_at: datetime | None = None
    cycles: int = 0
    # Supported ON intervals only: (seconds, watts), concatenated across pauses.
    power_intervals: list[tuple[float, float]] = field(default_factory=list)

    def record_power(self, seconds: float, watts: float) -> None:
        if seconds <= 0 or watts <= 0:
            return
        if self.power_intervals and self.power_intervals[-1][1] == watts:
            previous_seconds, _ = self.power_intervals[-1]
            self.power_intervals[-1] = (previous_seconds + seconds, watts)
        else:
            self.power_intervals.append((seconds, watts))

    def quarter_powers(self) -> tuple[float, float]:
        """Time-weighted quarters of supported ON time, excluding gaps and OFF pauses."""
        total = sum(seconds for seconds, _ in self.power_intervals)
        if total == 0:
            return self.watts, self.watts
        quarter = total / 4
        first = last = cursor = 0.0
        for seconds, watts in self.power_intervals:
            end = cursor + seconds
            first += max(0.0, min(end, quarter) - cursor) * watts
            last += max(0.0, end - max(cursor, total - quarter)) * watts
            cursor = end
        return first / quarter, last / quarter


@dataclass
class _Socket:
    latest_at: datetime | None = None
    latest_poll_at: datetime | None = None
    previous: EnergyReading | None = None
    last_ok: EnergyReading | None = None
    baseline_w: float = 0.0
    sessions: list[_Session] = field(default_factory=list)


class StepTracker:
    def __init__(
        self,
        *,
        household_id: UUID,
        threshold_w: float = 100.0,
        thermostat_band_w: float = 50.0,
        thermostat_gap: timedelta = timedelta(minutes=10),
        classify: Callable[[SessionFeatures], ApplianceMatch] | None = None,
        timezone: tzinfo = UTC,
        ownership_at: Callable[[UUID, datetime], ApplianceOwnership | None] | None = None,
        locate: Callable[[UUID], tuple[LocationKind, UUID | None]] | None = None,
    ) -> None:
        if not math.isfinite(threshold_w) or threshold_w <= 0:
            raise ValueError("threshold_w must be finite and positive")
        if not math.isfinite(thermostat_band_w) or thermostat_band_w < 0:
            raise ValueError("thermostat_band_w must be finite and nonnegative")
        if thermostat_gap < timedelta(0):
            raise ValueError("thermostat_gap must be nonnegative")
        self.household_id = household_id
        self.threshold_w = threshold_w
        self.thermostat_band_w = thermostat_band_w
        self.thermostat_gap = thermostat_gap
        self.classify = classify
        self.timezone = timezone
        self.ownership_at = ownership_at
        self.locate = locate
        self._sockets: dict[UUID, _Socket] = {}

    def _id(self, kind: str, device_id: UUID, at: datetime) -> UUID:
        return stable_id(
            "energy.steps", str(self.household_id), str(device_id), at.isoformat(), kind
        )

    def _consumption(
        self, device_id: UUID, session: _Session, *, closed: bool = False
    ) -> ConsumptionEvent:
        # Decimal accumulation; round once, ties to even, as in the common contracts.
        energy: EnergyWh = int(round(session.watt_seconds / Decimal(3600)))
        match = ApplianceMatch()
        owner = None
        if self.classify is not None:
            duration = None
            pattern = None
            if closed:
                assert session.stopped_at is not None
                duration = (session.stopped_at - session.started_at).total_seconds()
                first, last = session.quarter_powers()
                pattern = infer_pattern(
                    duration_s=duration,
                    cycles=session.cycles,
                    first_quarter_w=first,
                    last_quarter_w=last,
                )
            match = self.classify(
                SessionFeatures(
                    power_w=session.watts,
                    start_hour_local=session.started_at.astimezone(self.timezone).hour,
                    duration_s=duration,
                    pattern=pattern,
                )
            )
            if match.appliance_id is not None and self.ownership_at is not None:
                ownership = self.ownership_at(match.appliance_id, session.started_at)
                if ownership is not None and ownership.scope is ApplianceScope.personal:
                    owner = ownership.owner_resident_id
        return ConsumptionEvent(
            id=session.id,
            household_id=self.household_id,
            device_id=device_id,
            match=match,
            started_at=session.started_at,
            ended_at=session.stopped_at if closed else None,
            status=ConsumptionStatus.closed if closed else ConsumptionStatus.ongoing,
            peak_w=session.watts,
            energy_wh=energy,
            location=session.location,
            room_id=session.room_id,
            cost_estimate=None,
            appliance_owner_resident_id=owner,
            provenance=session.provenance,
        )

    def ingest(self, reading: EnergyReading) -> list[DomainEvent]:
        at = reading_time(reading)
        socket = self._sockets.setdefault(reading.device_id, _Socket())
        # Poll order rejects retries/late arrivals. A fresh stale poll can repeat
        # observed_at from the last OK contact: it must still break the series.
        if socket.latest_poll_at is not None and reading.ts <= socket.latest_poll_at:
            return []
        socket.latest_poll_at = reading.ts
        if not reading.usable:
            socket.previous = None
            socket.latest_at = max(socket.latest_at, at) if socket.latest_at is not None else at
            return []
        # Usable observations must also advance the measurement clock.
        if socket.latest_at is not None and at <= socket.latest_at:
            return []
        socket.latest_at = at

        events = self.tick(at)
        previous = socket.previous
        socket.previous = reading
        last_ok = socket.last_ok
        socket.last_ok = reading
        assert reading.power_w is not None
        if previous is None:
            active = [s for s in socket.sessions if s.stopped_at is None]
            if last_ok is not None:
                shortfall = socket.baseline_w + sum(s.watts for s in active) - reading.power_w
                while active and shortfall >= self.threshold_w:
                    session = min(active, key=lambda s: abs(s.watts - shortfall))
                    session.stopped_at = reading_time(last_ok)
                    session.provenance = Provenance.combine(
                        session.provenance, last_ok.provenance, reading.provenance
                    )
                    # Recovery is definitive, rather than a thermostat pause.
                    events.append(self._closed(reading.device_id, session, at))
                    socket.sessions.remove(session)
                    active.remove(session)
                    shortfall -= session.watts
            if not active:
                socket.baseline_w = reading.power_w
            return events
        assert previous.power_w is not None
        elapsed = at - reading_time(previous)
        seconds = Decimal(elapsed // timedelta(microseconds=1)) / Decimal(1_000_000)
        active = [s for s in socket.sessions if s.stopped_at is None]
        if not active:
            socket.baseline_w = previous.power_w
        for session in active:
            watts = (
                max(0.0, previous.power_w - socket.baseline_w)
                if len(active) == 1
                else session.watts
            )
            session.watt_seconds += Decimal(str(watts)) * seconds
            if self.classify is not None:
                session.record_power(float(seconds), watts)
            session.provenance = Provenance.combine(
                session.provenance, previous.provenance, reading.provenance
            )

        delta = reading.power_w - previous.power_w
        if abs(delta) < self.threshold_w:
            return events
        provenance = Provenance.combine(previous.provenance, reading.provenance)
        step = PowerStep(
            id=self._id("step", reading.device_id, at),
            device_id=reading.device_id,
            ts=at,
            before_w=previous.power_w,
            after_w=reading.power_w,
            provenance=provenance,
        )
        events.append(
            EnergyStepDetected(
                id=self._id("step_detected", reading.device_id, at),
                ts=at,
                household_id=self.household_id,
                correlation_id=step.id,
                provenance=provenance,
                data=step,
            )
        )
        if delta > 0:
            # Match the load's delta, not the total socket level: another load on
            # the extension may have changed meanwhile. Ties use opening order.
            waiting = [
                s
                for s in socket.sessions
                if s.stopped_at is not None
                and at <= s.stopped_at + self.thermostat_gap
                and abs(s.watts - delta) <= self.thermostat_band_w
            ]
            if waiting:
                session = min(waiting, key=lambda s: abs(s.watts - delta))
                session.cycles += 1
                session.stopped_at = None
                session.provenance = Provenance.combine(session.provenance, provenance)
            else:
                # Snapshot socket evidence at opening; a later configuration
                # change cannot move an already measured session to another room.
                location, room_id = (
                    self.locate(reading.device_id)
                    if self.locate is not None
                    else (LocationKind.unknown, None)
                )
                session = _Session(
                    id=self._id("session", reading.device_id, at),
                    started_at=at,
                    watts=delta,
                    provenance=provenance,
                    location=location,
                    room_id=room_id,
                )
                socket.sessions.append(session)
                data = self._consumption(reading.device_id, session)
                events.append(
                    EnergyConsumptionDetected(
                        id=self._id("consumption_detected", reading.device_id, at),
                        ts=at,
                        household_id=self.household_id,
                        correlation_id=session.id,
                        provenance=data.provenance,
                        data=data,
                    )
                )
        else:
            active = [s for s in socket.sessions if s.stopped_at is None]
            if active:
                # §6.7: one downward step stops the active load with the closest
                # opening delta, even when other loads keep the socket above its
                # original baseline. Do not stop all loads on an extension.
                session = min(active, key=lambda s: abs(s.watts + delta))
                session.stopped_at = at
                session.provenance = Provenance.combine(session.provenance, provenance)
        return events

    def _closed(self, device_id: UUID, session: _Session, at: datetime) -> EnergyConsumptionClosed:
        data = self._consumption(device_id, session, closed=True)
        return EnergyConsumptionClosed(
            id=stable_id("energy.steps", "closed", str(session.id)),
            ts=at,
            household_id=self.household_id,
            correlation_id=session.id,
            provenance=data.provenance,
            data=data,
        )

    def tick(self, now: datetime) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        due = [
            (s.stopped_at + self.thermostat_gap, device_id, socket, s)
            for device_id, socket in self._sockets.items()
            for s in socket.sessions
            if s.stopped_at is not None and now > s.stopped_at + self.thermostat_gap
        ]
        for deadline, device_id, socket, session in sorted(
            due, key=lambda item: (item[0], str(item[1]), str(item[3].id))
        ):
            # Use the deadline, not the polling time: replay stays identical.
            events.append(self._closed(device_id, session, deadline))
            socket.sessions.remove(session)
        return events
