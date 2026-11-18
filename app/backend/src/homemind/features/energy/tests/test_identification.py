"""ENERGY-04: regras puras do agrupamento e recálculo da assinatura a partir das amostras."""

import asyncio
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import stable_id
from homemind.contracts.devices import SignaturePattern
from homemind.contracts.energy import ApplianceIdentificationRequest, approx_power_w
from homemind.features.energy import identification as rules
from homemind.features.energy.learning import (
    SignatureBaseline,
    SignatureSample,
    rebuild_signature,
    signature_id_for,
)
from homemind.features.energy.tests.test_learning_consumer import (
    add_appliance,
    bus_for,
    deliver_session,
    signature,
)

A, B = stable_id("group", "a"), stable_id("group", "b")
T = fx.T0


@pytest.mark.parametrize(
    "power,reference,ok",
    [(850, 800, True), (881, 800, False), (2190, 2000, True), (2201, 2000, False)],
)
def test_power_tolerance_is_max_of_50_w_and_10_percent(power, reference, ok):
    assert rules.power_matches(power, reference) is ok


def test_duration_ratio_and_closest_group():
    assert rules.duration_matches(600, 1200) and not rules.duration_matches(599, 1200)
    groups = [rules.GroupSummary(B, 830, 600), rules.GroupSummary(A, 790, 600)]
    assert rules.choose_group(800, 700, groups) == A
    assert rules.choose_group(800, 100, groups) is None  # duração muito diferente
    assert rules.choose_group(1500, 600, groups) is None


def test_third_occurrence_in_seven_days_and_snooze():
    times = [T, T + timedelta(days=3), T + timedelta(days=7)]
    assert rules.occurrences(times, T + timedelta(days=7)) == 2  # a 1.ª já saiu da janela
    assert rules.occurrences(times, T + timedelta(days=6, hours=23)) == 2
    assert rules.should_ask(status="open", snoozed_until=None, count=3, at=T)
    assert not rules.should_ask(status="open", snoozed_until=None, count=2, at=T)
    assert not rules.should_ask(status="asked", snoozed_until=None, count=5, at=T)
    assert not rules.should_ask(status="resolved", snoozed_until=None, count=5, at=T)
    later = T + rules.SNOOZE
    assert not rules.should_ask(status="open", snoozed_until=later, count=3, at=T)
    assert rules.should_ask(status="open", snoozed_until=later, count=3, at=later)


def test_text_helpers_round_power_and_hour():
    assert [approx_power_w(w) for w in (12, 790, 824, 826, 2040)] == [50, 800, 800, 850, 2050]
    assert rules.usual_hour([8, 9, 9, 8, 7]) == 8
    assert rules.appliance_name(800) == "Aparelho ~800 W"
    with pytest.raises(ValueError):
        ApplianceIdentificationRequest(
            id=A, device_id=B, power_w=0, duration_s=60, hour_local=8, occurrences=3,
            expires_at=T, provenance=fx.SIM_INFERRED,
        )  # fmt: skip


def sample(power, pattern=SignaturePattern.continuous, hour=8, duration=600.0):
    return SignatureSample(power, duration, pattern, hour)


def test_rebuild_from_samples_baseline_and_lock():
    aid = stable_id("appliance", "x")
    sig, counts = rebuild_signature(
        aid,
        [sample(780), sample(820, SignaturePattern.cyclic, 9), sample(800, hour=8)],
        updated_at=T,
    )
    assert sig.id == signature_id_for(aid) and sig.origin.value == "learned"
    assert sig.samples == 3 and sig.watts_mean == 800 and sig.watts_tolerance == 80
    assert sig.pattern is SignaturePattern.continuous and sig.typical_hours == [8, 9]
    assert counts == {SignaturePattern.continuous: 2, SignaturePattern.cyclic: 1}
    base = SignatureBaseline(4, 1000, 300, (7,), {SignaturePattern.short: 4})
    sig, _ = rebuild_signature(aid, [sample(500)], baseline=base, updated_at=T)
    assert sig.samples == 5 and sig.watts_mean == 900 and sig.duration_typical_s == 360
    assert sig.pattern is SignaturePattern.short and sig.typical_hours == [7, 8]
    locked, _ = rebuild_signature(
        aid, [sample(500)], locked=SignaturePattern.decaying, updated_at=T
    )
    assert locked.pattern is SignaturePattern.decaying
    assert rebuild_signature(aid, [], updated_at=T) == (None, {})


def test_learning_records_one_sample_per_session_and_keeps_baseline(db):
    """ENERGY-01 continua igual e passa a gravar amostras; o agregado antigo é a base."""
    aid = add_appliance(db)

    async def run():
        bus = bus_for(db)
        await deliver_session(bus)
        await deliver_session(bus, number=1, watts=2200)

    asyncio.run(run())
    rows = db.run_sync(
        lambda c: c.execute(
            "SELECT origin_kind,power_w,revoked_at FROM energy_signature_sample"
            " WHERE appliance_id=? ORDER BY created_at",
            (str(aid),),
        ).fetchall()
    )
    assert [tuple(r) for r in rows] == [("learning", 2000, None), ("learning", 2200, None)]
    assert signature(db, aid)[0].samples == 2 and signature(db, aid)[0].watts_mean == 2100
    # Assinatura anterior à 0401: a base (3 sessões a 1000 W) soma-se às amostras novas.
    other = add_appliance(db, name="Forno", watts=3000)
    db.run_sync(
        lambda c: c.execute(
            "INSERT INTO energy_signature_baseline VALUES (?,3,1000,10800,'[1]','{\"cyclic\":3}')",
            (str(signature_id_for(other)),),
        )
    )
    asyncio.run(deliver_session(bus_for(db), number=2, watts=3000))
    [sig] = signature(db, other)
    assert sig.samples == 4 and sig.watts_mean == 1500 and sig.pattern.value == "cyclic"
    assert sig.typical_hours == [1, 12]
