"""Deterministic synthetic signatures; no hardware, network or wall clock."""

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.devices import ApplianceSignature, SignatureOrigin, SignaturePattern
from homemind.contracts.energy import ApplianceMatch, MatchOutcome
from homemind.features.energy.classifier import SessionFeatures, classify, explain

KETTLE = stable_id("classifier", "kettle")
HEATER = stable_id("classifier", "heater")


def signature(appliance_id=KETTLE, **changes):
    return ApplianceSignature(
        **(
            {
                "id": stable_id("signature", str(appliance_id)),
                "appliance_id": appliance_id,
                "watts_mean": 2000,
                "watts_tolerance": 100,
                "duration_typical_s": 180,
                "pattern": SignaturePattern.short,
                "origin": SignatureOrigin.simulated,
                "updated_at": fx.T0,
            }
            | changes
        )
    )


def kettle_and_heater():
    return {
        KETTLE: [signature()],
        HEATER: [signature(HEATER, duration_typical_s=7200, pattern=SignaturePattern.continuous)],
    }


@pytest.mark.parametrize(
    "duration,pattern,winner",
    [(180, SignaturePattern.short, KETTLE), (7200, SignaturePattern.continuous, HEATER)],
)
def test_two_kw_loads_ambiguous_at_start_identified_at_close(duration, pattern, winner):
    signatures = kettle_and_heater()
    provisional = classify(SessionFeatures(2000, 12), signatures)
    assert provisional.outcome is MatchOutcome.ambiguous
    assert provisional.appliance_id is provisional.confidence is None
    assert len(provisional.candidates) == 2
    final = classify(SessionFeatures(2000, 12, duration, pattern), signatures)
    assert final.appliance_id == winner
    assert final.confidence == 1.0
    assert ApplianceMatch.model_validate_json(final.model_dump_json()) == final


@pytest.mark.parametrize(
    "watts,score", [(2000, 1.0), (2050, 0.75), (2100, 0.5), (2150, 0.25), (2200, 0.0)]
)
def test_piecewise_power_and_missing_components_renormalize(watts, score):
    result = explain(SessionFeatures(watts, None), {KETTLE: [signature()]})
    assert result.candidates[0].confidence == score
    assert [(c.name, c.score, c.weight) for c in result.candidates[0].components] == [
        ("power", score, 0.5)
    ]


@pytest.mark.parametrize("watts", [1799.9, 2200.1])
def test_outside_twice_tolerance_excludes_signature(watts):
    match = classify(SessionFeatures(watts, 12), {KETTLE: [signature()]})
    assert match == ApplianceMatch()
    assert match.outcome is MatchOutcome.unknown


def test_no_signatures_and_zero_tolerance():
    assert classify(SessionFeatures(2000, None), {}) == ApplianceMatch()
    signatures = {KETTLE: [signature(watts_tolerance=0)]}
    assert classify(SessionFeatures(2000, None), signatures).confidence == 1
    assert classify(SessionFeatures(2000.001, None), signatures).candidates == []


@pytest.mark.parametrize("watts,identified", [(2080, True), (2080.2, False)])
def test_exact_confidence_threshold(watts, identified):
    match = classify(SessionFeatures(watts, None), {KETTLE: [signature()]})
    assert (match.appliance_id is not None) is identified
    if not identified:
        assert match.confidence is None
        assert match.outcome is MatchOutcome.unknown
        assert match.candidates == []  # abaixo de 0,6 não se listam candidatos (decisão)


@pytest.mark.parametrize("mean,identified", [(2030, True), (2029.8, False)])
def test_exact_margin_threshold(mean, identified):
    signatures = {KETTLE: [signature()], HEATER: [signature(HEATER, watts_mean=mean)]}
    match = classify(SessionFeatures(2000, None), signatures)
    assert (match.appliance_id == KETTLE) is identified
    if not identified:
        assert match.confidence is None
        assert match.outcome is MatchOutcome.ambiguous


def test_explanation_retains_low_confidence_reason_and_all_weights():
    signatures = {
        KETTLE: [signature(typical_hours=[12])],
        HEATER: [signature(HEATER, typical_hours=[12])],
    }
    result = explain(SessionFeatures(2100, 4, 360, SignaturePattern.continuous), signatures)
    assert result.outcome is MatchOutcome.unknown
    # 0.5*0.5 + 0.3*0.5 + 0.1*0 + 0.1*0 = 0.4.
    assert all(c.confidence == 0.4 for c in result.candidates)
    assert result.match.appliance_id is result.match.confidence is None
    # Decisão do utilizador: abaixo de 0,6 é `unknown`; os candidatos só ficam na explicação.
    assert result.match.candidates == []
    assert result.match.outcome is MatchOutcome.unknown
    assert len(result.candidates) == 2
    assert sum(c.weight for c in result.candidates[0].components) == pytest.approx(1)
    assert ApplianceMatch.model_validate_json(result.match.model_dump_json()) == result.match


@pytest.mark.parametrize("hour,winner", [(12, KETTLE), (0, HEATER)])
def test_habitual_hour_separates_otherwise_identical_heaters(hour, winner):
    signatures = {
        KETTLE: [signature(typical_hours=[12])],
        HEATER: [signature(HEATER, typical_hours=[0])],
    }
    match = classify(SessionFeatures(2000, hour), signatures)
    assert match.appliance_id == winner
    assert [c.confidence for c in match.candidates] == [1, 0.833]


def test_hour_alone_cannot_clear_final_margin_when_all_components_are_available():
    signatures = {
        KETTLE: [signature(typical_hours=[12])],
        HEATER: [signature(HEATER, typical_hours=[0])],
    }
    match = classify(SessionFeatures(2000, 12, 180, SignaturePattern.short), signatures)
    assert [c.confidence for c in match.candidates] == [1, 0.9]
    assert match.outcome is MatchOutcome.ambiguous
    assert match.appliance_id is match.confidence is None


@pytest.mark.parametrize("hour,score", [(23, 0.917), (1, 0.917), (2, 0.833)])
def test_adjacent_hours_wrap_midnight(hour, score):
    match = classify(SessionFeatures(2000, hour), {KETTLE: [signature(typical_hours=[0])]})
    assert match.confidence == score


@pytest.mark.parametrize("hours", [None, []])
def test_unavailable_signature_components_are_omitted(hours):
    sig = signature(typical_hours=hours, duration_typical_s=None)
    result = explain(SessionFeatures(2050, 12, 180, SignaturePattern.short), {KETTLE: [sig]})
    assert result.match.confidence == 0.792  # (0.5*0.75 + 0.1*1) / 0.6.
    assert [c.name for c in result.candidates[0].components] == ["power", "pattern"]


def test_best_signature_per_appliance_top_five_and_deterministic_ties():
    ids = [stable_id("candidate", str(i)) for i in range(7)]
    signatures = {aid: [signature(aid)] for aid in ids}
    worse = signature(ids[0], id=stable_id("worse"), watts_mean=2100)
    equal = signature(ids[0], id=stable_id("equal"))
    signatures[ids[0]] += [worse, equal]
    result = explain(SessionFeatures(2000, None), signatures)
    assert len(result.candidates) == 5
    assert [c.appliance_id for c in result.candidates] == sorted(ids, key=str)[:5]
    reversed_signatures = {
        aid: list(reversed(items)) for aid, items in reversed(signatures.items())
    }
    assert explain(SessionFeatures(2000, None), reversed_signatures) == result
    if ids[0] in [c.appliance_id for c in result.candidates]:
        candidate = next(c for c in result.candidates if c.appliance_id == ids[0])
        assert candidate.signature_id == min(signature(ids[0]).id, equal.id, key=str)


def test_candidates_are_sorted_by_score_and_zero_duration_is_valid():
    result = explain(
        SessionFeatures(2000, None, 0, SignaturePattern.short),
        {HEATER: [signature(HEATER, watts_mean=2050)], KETTLE: [signature()]},
    )
    assert [c.appliance_id for c in result.candidates] == [KETTLE, HEATER]
    assert [c.confidence for c in result.candidates] == [0.667, 0.528]
    assert result.outcome is MatchOutcome.ambiguous


def test_mismatched_catalogue_key_is_rejected():
    with pytest.raises(ValueError, match="mapping"):
        classify(SessionFeatures(2000, 12), {HEATER: [replace(signature(), appliance_id=KETTLE)]})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"power_w": -1},
        {"power_w": float("nan")},
        {"duration_s": float("inf")},
        {"duration_s": -1},
        {"start_hour_local": 24},
        {"start_hour_local": 1.5},
    ],
)
def test_invalid_features_are_rejected(kwargs):
    with pytest.raises(ValueError):
        SessionFeatures(**({"power_w": 2000, "start_hour_local": None} | kwargs))
