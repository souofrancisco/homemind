"""Synthetic appliance profiles; all times come from the input readings."""

from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, replace, stable_id
from homemind.contracts.devices import PowerUnit
from homemind.contracts.domain_events import (
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
    EnergyStepDetected,
)
from homemind.contracts.energy import (
    ConsumptionStatus,
    EnergyReading,
    LocationKind,
    MatchOutcome,
    ReadingStatus,
)
from homemind.features.energy.steps import StepTracker

SOCKET = stable_id("energy-tests", "socket")
OTHER_SOCKET = stable_id("energy-tests", "other-socket")


def reading(seconds, watts, *, status=ReadingStatus.ok, device_id=SOCKET):
    return EnergyReading(
        id=stable_id("energy-tests", str(device_id), str(seconds), status.value),
        device_id=device_id,
        ts=fx.T0 + timedelta(seconds=seconds),
        status=status,
        power_w=watts,
        raw_unit=PowerUnit.unknown if status is ReadingStatus.unit_unknown else PowerUnit.W,
        provenance=fx.SIM_MEASURED,
    )


@pytest.fixture
def tracker():
    return StepTracker(household_id=fx.HOUSEHOLD)


def feed(tracker, profile):
    return [
        event for seconds, watts in profile for event in tracker.ingest(reading(seconds, watts))
    ]


def of_type(events, cls):
    return [event for event in events if isinstance(event, cls)]


def test_first_reading_confirms_threshold_and_small_changes_update_baseline(tracker):
    assert tracker.ingest(reading(0, 0)) == []
    events = tracker.ingest(reading(30, 100))
    assert [type(e) for e in events] == [EnergyStepDetected, EnergyConsumptionDetected]
    assert events[0].data.before_w == 0
    assert events[0].data.after_w == 100
    assert events[0].ts == fx.T0 + timedelta(seconds=30)
    assert tracker.ingest(reading(60, 140)) == []
    events = tracker.ingest(reading(90, 240))
    assert events[0].data.before_w == 140
    assert events[0].data.delta_w == 100
    data = events[1].data
    assert data.status is ConsumptionStatus.ongoing
    assert data.match.outcome is MatchOutcome.unknown
    assert data.match.candidates == []
    assert data.location is LocationKind.unknown
    assert data.room_id is data.cost_estimate is data.appliance_owner_resident_id is None
    assert data.ended_at is None and data.peak_w == 100


def test_chargers_vary_between_9_and_141_w_without_large_individual_steps(tracker):
    # The range exceeds 100 W, but each consecutive change is at most 40 W.
    powers = [9, 49, 89, 129, 141, 101, 61, 21, 9]
    assert feed(tracker, [(i * 30, w) for i, w in enumerate(powers)]) == []


@pytest.mark.parametrize("status", list(ReadingStatus)[1:])
def test_gap_never_becomes_zero_or_produces_a_step(tracker, status):
    assert tracker.ingest(reading(0, 0)) == []
    assert tracker.ingest(reading(30, None, status=status)) == []
    assert tracker.ingest(reading(60, 2000)) == []
    assert tracker.ingest(reading(90, 2040)) == []
    assert tracker.tick(fx.T0 + timedelta(hours=1)) == []


def test_stale_power_is_not_usable(tracker):
    tracker.ingest(reading(0, 0))
    assert tracker.ingest(reading(30, 2000, status=ReadingStatus.stale)) == []
    assert tracker.ingest(reading(60, 2000)) == []


def test_stale_poll_with_repeated_observed_at_still_breaks_the_series(tracker):
    tracker.ingest(replace(reading(0, 0), observed_at=fx.T0))
    stale = replace(reading(30, 0, status=ReadingStatus.stale), observed_at=fx.T0)
    assert tracker.ingest(stale) == []
    assert tracker.ingest(reading(60, 2000)) == []


def test_heater_three_cycles_with_four_minute_pauses_are_one_session(tracker):
    events = feed(
        tracker,
        [(0, 0), (30, 1050), (150, 0), (390, 1050), (510, 0), (750, 1050), (870, 0)],
    )
    detected = of_type(events, EnergyConsumptionDetected)
    assert len(detected) == 1
    assert not of_type(events, EnergyConsumptionClosed)
    closed = tracker.tick(fx.T0 + timedelta(seconds=1471))
    assert len(closed) == 1
    assert closed[0].data.id == detected[0].data.id
    assert closed[0].data.ended_at == fx.T0 + timedelta(seconds=870)
    assert closed[0].data.energy_wh == 105  # 1050 W × 3 × 120 s / 3600.
    assert tracker.tick(fx.T0 + timedelta(hours=1)) == []


def test_twelve_minute_pause_closes_then_opens_a_new_session(tracker):
    events = feed(tracker, [(0, 0), (30, 1050), (150, 0), (870, 1050)])
    assert len(of_type(events, EnergyConsumptionDetected)) == 2
    assert [type(e) for e in events[-3:]] == [
        EnergyConsumptionClosed,
        EnergyStepDetected,
        EnergyConsumptionDetected,
    ]
    closed = of_type(events, EnergyConsumptionClosed)[0]
    assert closed.data.ended_at == fx.T0 + timedelta(seconds=150)
    assert closed.data.energy_wh == 35


@pytest.mark.parametrize("watts,expected_sessions", [(1000, 1), (1100, 1), (1101, 2)])
def test_thermostat_band_is_inclusive(tracker, watts, expected_sessions):
    events = feed(tracker, [(0, 0), (30, 1050), (60, 0), (300, watts)])
    assert len(of_type(events, EnergyConsumptionDetected)) == expected_sessions


def test_return_at_exactly_ten_minutes_is_same_session(tracker):
    events = feed(tracker, [(0, 0), (30, 1050), (60, 0)])
    assert tracker.tick(fx.T0 + timedelta(seconds=660)) == []
    events += tracker.ingest(reading(660, 1050))
    assert len(of_type(events, EnergyConsumptionDetected)) == 1
    assert not of_type(events, EnergyConsumptionClosed)


@pytest.mark.parametrize("watts,duration,expected_wh", [(2000, 180, 100), (600, 120, 20)])
def test_kettle_and_dryer_sample_and_hold(tracker, watts, duration, expected_wh):
    profile = [(0, 0)] + [(s, watts) for s in range(30, duration + 30, 30)]
    profile.append((duration + 30, 0))
    events = feed(tracker, profile)
    events += tracker.tick(fx.T0 + timedelta(seconds=duration + 631))
    closed = of_type(events, EnergyConsumptionClosed)
    assert len(closed) == 1
    # At most half a Wh is lost by the single final integer rounding. No
    # trapezoidal ramp: the last ON sample holds until the OFF sample.
    assert abs(closed[0].data.energy_wh - expected_wh) <= 0.5


@pytest.mark.parametrize("status", list(ReadingStatus)[1:])
def test_energy_does_not_cross_a_gap_or_count_until_missing_timestamp(tracker, status):
    feed(tracker, [(0, 0), (30, 2000), (60, 2000)])
    assert tracker.ingest(reading(90, None, status=status)) == []
    assert tracker.ingest(reading(600, 2000)) == []
    tracker.ingest(reading(630, 0))
    closed = tracker.tick(fx.T0 + timedelta(seconds=1231))
    # Only [30,60) and [600,630) are supported: 2000 × 60 / 3600.
    assert closed[0].data.energy_wh == 33


@pytest.mark.parametrize("status", list(ReadingStatus)[1:])
def test_load_off_during_gap_closes_at_last_ok_without_phantom_energy(tracker, status):
    opened = feed(tracker, [(0, 0), (30, 2000), (60, 2000)])
    assert tracker.ingest(reading(90, None, status=status)) == []
    assert tracker.ingest(reading(120, None, status=status)) == []
    recovered = tracker.ingest(reading(150, 0))
    assert [type(e) for e in recovered] == [EnergyConsumptionClosed]
    closed = recovered[0]
    assert closed.data.id == of_type(opened, EnergyConsumptionDetected)[0].data.id
    assert closed.data.status is ConsumptionStatus.closed
    assert closed.data.ended_at == fx.T0 + timedelta(seconds=60)
    assert closed.data.energy_wh == 17  # Only [30,60): 2000 W × 30 s.
    assert closed.ts == fx.T0 + timedelta(seconds=150)
    assert feed(tracker, [(150 + i * 30, 0) for i in range(1, 60)]) == []
    assert tracker.tick(fx.T0 + timedelta(hours=2)) == []
    # Recovery removed the session; it cannot be resumed as a thermostat cycle.
    restarted = tracker.ingest(reading(7230, 2000))
    detected = of_type(restarted, EnergyConsumptionDetected)
    assert len(detected) == 1
    assert detected[0].data.id != closed.data.id


def test_heater_still_on_after_gap_keeps_session_and_skips_gap_energy(tracker):
    opened = feed(tracker, [(0, 0), (30, 2000), (60, 2000)])
    tracker.ingest(reading(90, None, status=ReadingStatus.missing))
    tracker.ingest(reading(120, None, status=ReadingStatus.missing))
    assert tracker.ingest(reading(600, 2000)) == []
    assert tracker.tick(fx.T0 + timedelta(hours=2)) == []
    tracker.ingest(reading(630, 0))
    closed = tracker.tick(fx.T0 + timedelta(hours=2))
    assert len(closed) == 1
    assert closed[0].data.id == of_type(opened, EnergyConsumptionDetected)[0].data.id
    assert closed[0].data.ended_at == fx.T0 + timedelta(seconds=630)
    assert closed[0].data.energy_wh == 33


def test_only_kettle_closes_when_heater_survives_gap(tracker):
    opened = feed(tracker, [(0, 50), (30, 1050), (60, 3050), (90, 3050)])
    heater, kettle = of_type(opened, EnergyConsumptionDetected)
    tracker.ingest(reading(120, None, status=ReadingStatus.missing))
    recovered = tracker.ingest(reading(600, 1050))
    assert [type(e) for e in recovered] == [EnergyConsumptionClosed]
    assert recovered[0].data.id == kettle.data.id
    assert recovered[0].data.ended_at == fx.T0 + timedelta(seconds=90)
    assert recovered[0].data.energy_wh == 17
    tracker.ingest(reading(630, 50))
    closed = tracker.tick(fx.T0 + timedelta(seconds=1231))
    assert len(closed) == 1
    assert closed[0].data.id == heater.data.id
    assert closed[0].data.energy_wh == 25  # 1000 W × (60 + 30) s.


def test_gap_reconciliation_repeats_closest_delta_and_uses_opening_order(tracker):
    opened = feed(tracker, [(0, 0), (30, 1000), (60, 2000), (90, 4000), (120, 4000)])
    first, second, kettle = of_type(opened, EnergyConsumptionDetected)
    tracker.ingest(reading(150, None, status=ReadingStatus.missing))
    recovered = tracker.ingest(reading(600, 1000))
    assert [type(e) for e in recovered] == [EnergyConsumptionClosed] * 2
    assert [e.data.id for e in recovered] == [kettle.data.id, first.data.id]
    assert all(e.data.ended_at == fx.T0 + timedelta(seconds=120) for e in recovered)
    tracker.ingest(reading(630, 0))
    closed = tracker.tick(fx.T0 + timedelta(seconds=1231))
    assert [e.data.id for e in closed] == [second.data.id]
    assert closed[0].data.energy_wh == 25


@pytest.mark.parametrize("recovered_w,closes", [(900, True), (901, False)])
def test_gap_shortfall_threshold_is_inclusive(tracker, recovered_w, closes):
    feed(tracker, [(0, 0), (30, 1000), (60, 1000)])
    tracker.ingest(reading(90, None, status=ReadingStatus.missing))
    recovered = tracker.ingest(reading(120, recovered_w))
    assert not of_type(recovered, EnergyStepDetected)
    assert len(of_type(recovered, EnergyConsumptionClosed)) == int(closes)


@pytest.mark.parametrize(
    "powers,expected_wh",
    [([600, 550, 500, 450, 400], 208), ([120, 100, 80, 60, 40], 33)],
)
def test_single_variable_load_integrates_measured_power_above_baseline(
    tracker, powers, expected_wh
):
    # Subthreshold changes keep one session; the 50 W background is excluded.
    profile = [(0, 50)] + [(30 + i * 300, 50 + w) for i, w in enumerate(powers)]
    events = feed(tracker, profile + [(1530, 50 + powers[-1])])
    assert len(of_type(events, EnergyConsumptionDetected)) == 1
    assert len(of_type(events, EnergyStepDetected)) == 1
    tracker.ingest(reading(1560, None, status=ReadingStatus.missing))
    closed = tracker.ingest(reading(1590, 0))
    assert [type(e) for e in closed] == [EnergyConsumptionClosed]
    # Integrate all five held readings up to the last OK at 1530 s.
    assert closed[0].data.energy_wh == expected_wh


def test_single_session_measured_power_is_clamped_to_zero(tracker):
    feed(tracker, [(0, 50), (30, 170), (60, 90), (90, 10), (390, 10)])
    tracker.ingest(reading(420, None, status=ReadingStatus.missing))
    closed = tracker.ingest(reading(450, 0))
    assert closed[0].data.energy_wh == 1  # (120 + 40) W × 30 s, no negative energy.


def test_overlapping_sessions_integrate_their_deltas_despite_measured_variation(tracker):
    opened = feed(tracker, [(0, 50), (30, 650), (60, 770), (90, 720), (120, 670), (360, 670)])
    first, second = of_type(opened, EnergyConsumptionDetected)
    tracker.ingest(reading(390, None, status=ReadingStatus.missing))
    closed = tracker.ingest(reading(420, 50))
    assert [type(e) for e in closed] == [EnergyConsumptionClosed] * 2
    assert [e.data.id for e in closed] == [first.data.id, second.data.id]
    assert [e.data.energy_wh for e in closed] == [55, 10]


def test_simultaneous_loads_stop_the_closest_delta_only(tracker):
    events = feed(tracker, [(0, 0), (30, 1050), (60, 3050), (240, 1050)])
    detected = of_type(events, EnergyConsumptionDetected)
    assert [e.data.peak_w for e in detected] == [1050, 2000]
    closed = tracker.tick(fx.T0 + timedelta(seconds=841))
    assert len(closed) == 1
    assert closed[0].data.id == detected[1].data.id
    assert closed[0].data.energy_wh == 100
    tracker.ingest(reading(900, 0))
    heater = tracker.tick(fx.T0 + timedelta(seconds=1501))
    assert heater[0].data.id == detected[0].data.id
    assert heater[0].data.energy_wh == 254  # 1050 × (900 - 30) / 3600, rounded once.


def test_equal_loads_use_opening_order_for_ties(tracker):
    events = feed(tracker, [(0, 0), (30, 1000), (60, 2000), (90, 1000)])
    detected = of_type(events, EnergyConsumptionDetected)
    closed = tracker.tick(fx.T0 + timedelta(seconds=691))
    assert closed[0].data.id == detected[0].data.id


def test_socket_states_are_independent(tracker):
    tracker.ingest(reading(0, 0))
    assert tracker.ingest(reading(30, 2000, device_id=OTHER_SOCKET)) == []
    events = tracker.ingest(reading(60, 1050))
    assert events[0].data.delta_w == 1050
    assert all(e.data.device_id == SOCKET for e in events)


def test_simulated_provenance_combines_and_replay_is_identical():
    def replay():
        tracker = StepTracker(household_id=fx.HOUSEHOLD)
        tracker.ingest(replace(reading(0, 0), provenance="measured"))
        events = tracker.ingest(reading(30, 2000))
        events += tracker.ingest(replace(reading(60, 2000), provenance=fx.SIM_ESTIMATED))
        events += tracker.ingest(reading(210, 0))
        events += tracker.tick(fx.T0 + timedelta(seconds=811))
        return events

    first = replay()
    assert first == replay()  # Includes payload, envelope and correlation IDs.
    assert all(e.provenance.origin is Origin.simulated for e in first)
    assert all(e.provenance == e.data.provenance for e in first)
    closed = of_type(first, EnergyConsumptionClosed)[0]
    assert closed.provenance == Provenance(origin=Origin.simulated, kind=ValueKind.estimated)


def test_observed_at_overrides_poll_timestamp_and_late_readings_are_ignored(tracker):
    baseline = replace(reading(300, 0), observed_at=fx.T0)
    start = replace(reading(330, 2000), observed_at=fx.T0 + timedelta(seconds=30))
    tracker.ingest(baseline)
    events = tracker.ingest(start)
    assert events[0].ts == events[1].data.started_at == fx.T0 + timedelta(seconds=30)
    assert tracker.ingest(start) == []
    assert tracker.ingest(reading(15, 4000)) == []
    assert tracker.ingest(reading(30, None, status=ReadingStatus.missing)) == []
    down = tracker.ingest(replace(reading(510, 0), observed_at=fx.T0 + timedelta(seconds=210)))
    assert down[0].data.before_w == 2000
    closed = tracker.tick(fx.T0 + timedelta(seconds=811))
    assert closed[0].data.energy_wh == 100


def test_closure_timestamp_does_not_depend_on_tick_frequency():
    def close(seconds):
        tracker = StepTracker(household_id=fx.HOUSEHOLD)
        feed(tracker, [(0, 0), (30, 2000), (210, 0)])
        return tracker.tick(fx.T0 + timedelta(seconds=seconds))

    assert close(811) == close(3600)


def test_custom_threshold_and_timeout():
    tracker = StepTracker(
        household_id=fx.HOUSEHOLD, threshold_w=200, thermostat_gap=timedelta(minutes=1)
    )
    events = feed(tracker, [(0, 0), (30, 100), (60, 300), (90, 100)])
    assert len(of_type(events, EnergyStepDetected)) == 2
    assert len(tracker.tick(fx.T0 + timedelta(seconds=151))) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold_w": 0},
        {"threshold_w": float("nan")},
        {"thermostat_band_w": -1},
        {"thermostat_band_w": float("inf")},
        {"thermostat_gap": timedelta(seconds=-1)},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        StepTracker(household_id=fx.HOUSEHOLD, **kwargs)
