"""Fusão (lógica pura, relógio simulado): em casa / fora / incerto com tolerância."""

from datetime import UTC, datetime, timedelta

import pytest

from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.presence import (
    DoorCrossed,
    DoorDirection,
    PresenceEvent,
    PresenceSource,
    PresenceState,
    UncertainReason,
)
from homemind.features.presence.fusion import FusionParams, Signals, fuse

T0 = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)
R, OTHER = stable_id("resident", "r"), stable_id("resident", "outro")
HOUSE = stable_id("household", "h")
INF = Provenance(origin=Origin.real, kind=ValueKind.inferred)
MEAS = Provenance(origin=Origin.real, kind=ValueKind.measured)
SIM = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
P = FusionParams()  # tolerância 25 min


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


_n = iter(range(10**6))


def cue(m, source="wifi", state="in", who=R, prov=None):
    src = PresenceSource(source)
    return PresenceEvent(
        id=stable_id("cue", str(next(_n))),
        household_id=HOUSE,
        resident_id=who,
        ts=at(m),
        state=PresenceState(state),
        source=src,
        confidence={"wifi": 0.8, "manual": 1.0, "appliance": 0.6}[source],
        provenance=prov or (MEAS if source == "manual" else INF),
        consumption_event_id=stable_id("c", str(next(_n))) if src is PresenceSource.appliance
        else None,
    )  # fmt: skip


def door(m, direction="out", conf=0.9, prov=INF):
    return DoorCrossed(
        ts=at(m), direction=DoorDirection(direction), confidence=conf, provenance=prov
    )


def state(cues, doors, now, **kw):
    v = fuse(R, cues, doors, at(now), P, **kw)
    return v


# --- em casa ---------------------------------------------------------------------------------


def test_no_cues_means_no_verdict_not_out():
    assert state([], [], 10).presence is None
    assert state([], [door(1, "in"), door(5, "out")], 60).presence is None  # a porta é anónima


def test_phone_asleep_10_min_without_crossing_the_door_stays_in():
    v = state([cue(0)], [], 10)
    assert v.presence.state is PresenceState.home and not v.ask
    assert v.presence.sources == [PresenceSource.wifi] and v.presence.confidence == 0.8
    assert v.presence.since == at(0)


def test_silence_never_turns_into_out_without_the_door():
    """Falha do Wi-Fi/câmara: horas sem pistas nem saída pela porta continuam «em casa»."""
    v = state([cue(0)], [], 60 * 30)
    assert v.presence.state is PresenceState.home
    assert v.presence.confidence <= 0.6  # menos confiança, mesmo estado
    v = state([cue(0)], [door(0.5, "in")], 600, signals=Signals(wifi_expected=True, wifi_ok=False))
    assert v.presence.state is PresenceState.home


def test_low_confidence_door_events_are_ignored():
    v = state([cue(0)], [door(5, "out", conf=0.3)], 120)
    assert v.presence.state is PresenceState.home


def test_appliance_turning_on_proves_in_from_unknown():
    v = state([cue(0, "appliance")], [], 1)
    assert v.presence.state is PresenceState.home
    assert v.presence.sources == [PresenceSource.appliance]


# --- saída pela porta + tolerância -------------------------------------------------------------


def test_door_exit_plus_tolerance_becomes_out_only_after_the_tolerance():
    cues, doors = [cue(0)], [door(5, "out")]
    just_before = state(cues, doors, 5 + 24.9)
    assert just_before.presence.state is PresenceState.home  # ainda a contar
    assert just_before.presence.confidence == 0.5
    assert PresenceSource.camera_door in just_before.presence.sources
    v = state(cues, doors, 5 + 25)
    assert v.presence.state is PresenceState.away and not v.ask
    assert v.presence.since == at(30)
    assert v.presence.sources == [PresenceSource.camera_door]
    assert v.presence.confidence == 0.7


def test_a_cue_during_the_tolerance_shows_the_exit_was_someone_else():
    v = state([cue(0), cue(15)], [door(5, "out")], 120)
    assert v.presence.state is PresenceState.home and v.presence.since == at(0)


def test_tolerance_is_configurable_between_20_and_30_minutes():
    p20 = FusionParams(tolerance=timedelta(minutes=20))
    assert fuse(R, [cue(0)], [door(5)], at(24.9), p20).presence.state is PresenceState.home
    assert fuse(R, [cue(0)], [door(5)], at(25), p20).presence.state is PresenceState.away


def test_door_exit_alone_never_says_out_for_someone_never_seen_in():
    assert state([], [door(5, "out")], 200).presence is None


def test_wifi_failure_makes_the_exit_unattributable_so_never_a_wrong_out():
    sig = Signals(wifi_expected=True, wifi_ok=False)
    v = state([cue(0)], [door(5)], 60, signals=sig)
    assert v.presence.state is PresenceState.uncertain and v.ask
    assert v.presence.reason is UncertainReason.no_recent_cues
    # com o Wi-Fi vivo, o silêncio já é informativo
    ok = Signals(wifi_expected=True, wifi_ok=True)
    assert state([cue(0)], [door(5)], 60, signals=ok).presence.state is PresenceState.away


def test_exit_with_other_residents_home_and_no_wifi_is_a_question_not_an_out():
    sig = Signals(wifi_expected=False, sole_candidate=False)
    v = state([cue(0, "manual")], [door(5)], 60, signals=sig)
    assert v.presence.state is PresenceState.uncertain and v.ask
    # um morador que pode refutar a dúvida a qualquer momento
    v = state([cue(0, "manual"), cue(61, "manual")], [door(5)], 62, signals=sig)
    assert v.presence.state is PresenceState.home


# --- declaração manual -------------------------------------------------------------------------


def test_manual_out_is_out_immediately_and_manual_in_brings_back():
    v = state([cue(0), cue(3, "manual", "out")], [], 4)
    assert v.presence.state is PresenceState.away and v.presence.confidence == 1.0
    assert v.presence.provenance == MEAS  # P-19: declaração = medida
    v = state([cue(0), cue(3, "manual", "out"), cue(10, "manual")], [], 11)
    assert v.presence.state is PresenceState.home and v.presence.since == at(10)


# --- contradição -------------------------------------------------------------------------------


def test_appliance_turning_on_after_manual_out_without_an_entry_is_a_question():
    v = state([cue(0, "manual", "out"), cue(20, "appliance")], [], 21)
    assert v.presence.state is PresenceState.uncertain and v.ask
    assert v.presence.reason is UncertainReason.conflicting_cues
    assert v.presence.since == at(20)
    assert v.presence.sources == [PresenceSource.appliance]


def test_wifi_cue_after_out_by_door_without_an_entry_is_a_question():
    v = state([cue(0), cue(40)], [door(5)], 41)  # saiu (30 min), o telemóvel aparece sem entrada
    assert v.presence.state is PresenceState.uncertain and v.ask


def test_an_entry_through_the_door_explains_the_return():
    base = [cue(0, "manual", "out"), cue(20, "appliance")]
    assert state(base, [door(19, "in")], 21).presence.state is PresenceState.home
    assert state(base, [door(21.5, "in")], 22).presence.state is PresenceState.home  # ≤ janela
    late = state(base, [door(25, "in")], 26)  # câmara tarde demais: continua a dúvida
    assert late.presence.state is PresenceState.uncertain
    # e a entrada que chega depois da pista (dentro da janela), quando já estava em dúvida
    v = state(base, [door(21, "in")], 21.5)
    assert v.presence.state is PresenceState.home
    assert PresenceSource.camera_door in v.presence.sources


def test_an_old_entry_before_leaving_does_not_explain_a_return():
    base = [cue(10, "manual", "out"), cue(20, "wifi")]
    assert state(base, [door(2, "in")], 21).presence.state is PresenceState.uncertain


def test_manual_answer_resolves_the_doubt():
    base = [cue(0, "manual", "out"), cue(20, "appliance")]
    v = state([*base, cue(22, "manual")], [], 23)
    assert v.presence.state is PresenceState.home and v.presence.sources == [PresenceSource.manual]
    v = state([*base, cue(22, "manual", "out")], [], 23)
    assert v.presence.state is PresenceState.away


def test_uncertain_since_does_not_move_with_repeated_conflicting_cues():
    cues = [cue(0, "manual", "out"), cue(20, "wifi"), cue(25, "wifi"), cue(30, "wifi")]
    assert state(cues, [], 31).presence.since == at(20)


# --- cues of others, provenance, window ---------------------------------------------------------


def test_only_the_residents_own_cues_count():
    v = state([cue(0, who=OTHER)], [], 5)
    assert v.presence is None


def test_provenance_is_simulated_if_any_input_is_and_inference_wins_over_measured():
    v = state([cue(0, prov=SIM)], [], 1)
    assert v.presence.provenance.origin is Origin.simulated
    v = state([cue(0, "manual", prov=MEAS)], [door(3)], 40)  # fora por porta: inferido
    assert v.presence.state is PresenceState.away
    assert v.presence.provenance.kind is ValueKind.inferred


def test_since_is_kept_when_the_window_start_slides():
    first = fuse(R, [cue(0)], [], at(10), P).presence
    later = fuse(R, [cue(60 * 40)], [], at(60 * 40 + 5), P, previous=first).presence
    assert later.since == first.since  # mesmo estado: `since` não anda com a janela
    other = fuse(R, [cue(0, "manual", "out")], [], at(5), P, previous=first).presence
    assert other.since == at(0) and other.state is PresenceState.away


@pytest.mark.parametrize("m", [0, 7, 24.9])
def test_pure_function_is_deterministic(m):
    args = ([cue(0)], [door(5)], at(m), P)
    assert fuse(R, *args) == fuse(R, *args)
