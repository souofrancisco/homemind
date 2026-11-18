"""Pure learning rules with fixed simulated observations."""

from dataclasses import replace
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.appliance_catalog import ApplianceSnapshot
from homemind.contracts.common import replace as contract_replace
from homemind.contracts.common import stable_id
from homemind.contracts.devices import ApplianceOwnership, SignaturePattern
from homemind.features.energy.learning import (
    SessionObservation,
    assign_appliance,
    learn,
    observe_session,
)

AID = stable_id("learning", "heater")


def observation(**changes):
    return replace(
        SessionObservation(
            device_id=fx.reading().device_id,
            started_at=fx.T0,
            ended_at=fx.T0 + timedelta(hours=3),
            peak_w=2000,
            duration_s=10800,
            cycles=1,
            first_quarter_w=2000,
            last_quarter_w=2000,
            appliance_id=AID,
        ),
        **changes,
    )


def snapshot(aid=AID, watts=2000, meter=None):
    return ApplianceSnapshot(aid, ApplianceOwnership(scope="common"), watts, meter)


def test_assignment_link_priority_and_unique_power_fallback():
    obs = observation()
    other = stable_id("learning", "kettle")
    assert assign_appliance(obs, [snapshot(meter=obs.device_id), snapshot(other)]) == AID
    assert assign_appliance(obs, [snapshot()]) == AID
    assert assign_appliance(obs, [snapshot(), snapshot(other, 2050)]) is None
    assert assign_appliance(obs, [snapshot(watts=None)]) is None
    assert assign_appliance(obs, []) is None
    assert assign_appliance(obs, [snapshot(watts=1800)]) is None
    assert assign_appliance(observation(peak_w=2200), [snapshot()]) == AID
    shared = [snapshot(meter=obs.device_id), snapshot(other, 2050, obs.device_id)]
    assert assign_appliance(obs, shared) is None
    shared = [snapshot(meter=obs.device_id), snapshot(other, 1000, obs.device_id)]
    assert assign_appliance(obs, shared) == AID


def test_three_sessions_accumulate_mean_modal_pattern_hours_and_lock():
    sig, counts = None, {}
    for watts, cycles, hour in [(1800, 1, 19), (2000, 1, 8), (2200, 0, 19)]:
        sig, counts = learn(
            sig,
            observation(peak_w=watts, cycles=cycles),
            pattern_counts=counts,
            locked=None,
            hour_local=hour,
        )
    assert sig.id == stable_id("energy.signature", str(AID))
    assert sig.samples == 3 and sig.watts_mean == 2000 and sig.watts_tolerance == 200
    assert sig.pattern is SignaturePattern.cyclic
    assert sig.duration_typical_s == 10800 and sig.typical_hours == [8, 19]
    assert sig.origin.value == "learned"
    locked, new_counts = learn(
        sig,
        observation(peak_w=2400),
        pattern_counts=counts,
        locked=SignaturePattern.short,
        hour_local=10,
    )
    assert locked.pattern is SignaturePattern.short and locked.watts_mean == 2100
    assert locked.samples == 4 and new_counts[SignaturePattern.cyclic] == 3
    assert counts[SignaturePattern.cyclic] == 2  # no mutation of caller state


def test_sample_hold_cycles_and_on_time_quarters():
    event = contract_replace(
        fx.consumption(),
        started_at=fx.T0,
        ended_at=fx.T0 + timedelta(seconds=1200),
        status="closed",
        peak_w=2000,
        energy_wh=500,
        cost_estimate=None,
    )
    readings = [
        contract_replace(fx.reading(w, fx.T0 + timedelta(seconds=t)), device_id=event.device_id)
        for t, w in [(0, 2100), (300, 100), (600, 2100), (900, 1500), (1200, 100)]
    ]
    obs = observe_session(event, readings, 100)
    assert obs.cycles == 1 and obs.duration_s == 1200
    assert obs.first_quarter_w == 2000 and obs.last_quarter_w == 1400
    assert observe_session(event, [], 100) is None
    bad = [contract_replace(r, status="missing", power_w=None) for r in readings]
    assert observe_session(event, bad, 100) is None


@pytest.mark.parametrize(
    "duration,cycles,first,last,expected",
    [
        (299, 1, 2000, 1000, "short"),
        (300, 1, 2000, 2000, "cyclic"),
        (600, 0, 2000, 1399, "decaying"),
        (600, 0, 2000, 1400, "continuous"),
    ],
)
def test_pattern_boundaries(duration, cycles, first, last, expected):
    sig, _ = learn(
        None,
        observation(duration_s=duration, cycles=cycles, first_quarter_w=first, last_quarter_w=last),
        pattern_counts={},
        locked=None,
        hour_local=0,
    )
    assert sig.pattern.value == expected
