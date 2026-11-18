"""Explainable weighted nearest neighbour over appliance signatures (pure).

Power: delta = abs(power_w - watts_mean), tolerance = watts_tolerance.
For delta <= tolerance, score = 1 - 0.5 * delta / tolerance; up to twice
tolerance, score = 0.5 * (2 * tolerance - delta) / tolerance. Beyond that
the signature is excluded. Zero tolerance admits only an exact match (score 1).
Duration: min(d, D) / max(d, D), only when both durations are available.
Pattern: 1 for equality, otherwise 0, only when the session pattern is available.
Hour: 1 inside typical_hours, 0.5 at circular distance one hour, otherwise 0.
Missing hours (including an empty list) omit the hour component.

Weights are power 0.5, duration 0.3, pattern 0.1 and hour 0.1; available
weights renormalize. Confidence is their weighted mean rounded to three places
(Python round, ties to even). Thresholds apply to these published scores:
best < 0.6 is unknown; best minus runner-up < 0.15 is ambiguous. Integer
thousandths avoid floating-point errors at the exact margin. Each appliance
keeps its best signature; ties use signature UUID, then appliance UUID for
ranking. At most five appliances are returned, with all components available
through explain(). No score determines billing or location.

The contract derives outcome from candidate count: multiple low-confidence
candidates therefore have match.outcome=ambiguous. Explanation.outcome retains
the classifier's unknown reason, without dropping candidates or changing contracts.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from homemind.contracts.devices import ApplianceSignature, SignaturePattern
from homemind.contracts.energy import ApplianceCandidate, ApplianceMatch, MatchOutcome


@dataclass(frozen=True)
class SessionFeatures:
    power_w: float
    start_hour_local: int | None
    duration_s: float | None = None
    pattern: SignaturePattern | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.power_w) or self.power_w < 0:
            raise ValueError("power_w must be finite and nonnegative")
        if self.start_hour_local is not None and (
            type(self.start_hour_local) is not int or not 0 <= self.start_hour_local <= 23
        ):
            raise ValueError("start_hour_local must be an integer from 0 to 23")
        if self.duration_s is not None and (not isfinite(self.duration_s) or self.duration_s < 0):
            raise ValueError("duration_s must be finite and nonnegative")


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    score: float
    weight: float


@dataclass(frozen=True)
class CandidateExplanation:
    appliance_id: UUID
    signature_id: UUID
    components: tuple[ScoreComponent, ...]
    confidence: float


@dataclass(frozen=True)
class Explanation:
    match: ApplianceMatch
    outcome: MatchOutcome
    candidates: tuple[CandidateExplanation, ...]


def _score(features: SessionFeatures, signature: ApplianceSignature) -> CandidateExplanation | None:
    delta = abs(features.power_w - signature.watts_mean)
    tolerance = signature.watts_tolerance
    if delta > 2 * tolerance:
        return None
    power = 1.0 if tolerance == 0 else max(0.0, 1 - 0.5 * delta / tolerance)
    components = [ScoreComponent("power", power, 0.5)]
    if features.duration_s is not None and signature.duration_typical_s is not None:
        d, typical = features.duration_s, signature.duration_typical_s
        components.append(ScoreComponent("duration", min(d, typical) / max(d, typical), 0.3))
    if features.pattern is not None:
        components.append(
            ScoreComponent("pattern", float(features.pattern == signature.pattern), 0.1)
        )
    if features.start_hour_local is not None and signature.typical_hours:
        distance = min(
            min(abs(features.start_hour_local - hour), 24 - abs(features.start_hour_local - hour))
            for hour in signature.typical_hours
        )
        hour_score = 1.0 if distance == 0 else 0.5 if distance == 1 else 0.0
        components.append(ScoreComponent("hour", hour_score, 0.1))
    total_weight = sum(c.weight for c in components)
    return CandidateExplanation(
        signature.appliance_id,
        signature.id,
        tuple(components),
        round(sum(c.weight * c.score for c in components) / total_weight, 3),
    )


def explain(
    features: SessionFeatures, signatures: Mapping[UUID, list[ApplianceSignature]]
) -> Explanation:
    """Return the match, decision reason and best signature's components per candidate.

    Mapping keys must agree with signature.appliance_id; inconsistent catalogues
    are rejected rather than silently identifying a different appliance.
    """
    best: dict[UUID, CandidateExplanation] = {}
    for appliance_id, items in signatures.items():
        for signature in items:
            if appliance_id != signature.appliance_id:
                raise ValueError("signature does not belong to mapping appliance")
            candidate = _score(features, signature)
            if candidate is None:
                continue
            previous = best.get(appliance_id)
            if previous is None or (-candidate.confidence, str(candidate.signature_id)) < (
                -previous.confidence,
                str(previous.signature_id),
            ):
                best[appliance_id] = candidate
    ranked = sorted(best.values(), key=lambda c: (-c.confidence, str(c.appliance_id)))[:5]
    scores = [round(c.confidence * 1000) for c in ranked]
    outcome = MatchOutcome.unknown
    if scores and scores[0] >= 600:
        outcome = (
            MatchOutcome.ambiguous
            if len(scores) > 1 and scores[0] - scores[1] < 150
            else MatchOutcome.identified
        )
    winner = ranked[0] if outcome is MatchOutcome.identified else None
    match = ApplianceMatch(
        appliance_id=winner.appliance_id if winner else None,
        confidence=winner.confidence if winner else None,
        # Decisão do utilizador: abaixo de 0,6 o resultado é `unknown`, por isso não se listam
        # candidatos (o contrato chamaria `ambiguous` a mais de um). A explicação mantém-nos.
        candidates=[
            ApplianceCandidate(appliance_id=c.appliance_id, confidence=c.confidence) for c in ranked
        ]
        if outcome is not MatchOutcome.unknown
        else [],
    )
    return Explanation(match, outcome, tuple(ranked))


def classify(
    features: SessionFeatures, signatures: Mapping[UUID, list[ApplianceSignature]]
) -> ApplianceMatch:
    """Identify only a sufficiently confident winner separated from the runner-up."""
    return explain(features, signatures).match
