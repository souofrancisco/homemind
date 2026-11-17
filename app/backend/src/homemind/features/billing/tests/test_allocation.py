"""Repartição (BILL-02) e arredondamento (BILL-04): fixtures do PDF (SIMULADAS) e propriedades."""

import random
from datetime import timedelta
from fractions import Fraction

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import (
    Attribution,
    AttributionMethod,
    AttributionStatus,
    AttributionTarget,
    BillInconsistentError,
    BreakdownKind,
)
from homemind.contracts.common import Audit, replace, stable_id
from homemind.contracts.energy import ConsumptionStatus
from homemind.features.billing.allocation import (
    EnergyShare,
    allocate,
    largest_remainder,
    shares_from_attributions,
)

ROOMS = {
    fx.ANA: fx.ROOM_ANA,
    fx.BRUNO: fx.ROOM_BRUNO,
    fx.CARLA: fx.ROOM_CARLA,
    fx.DIOGO: fx.ROOM_DIOGO,
}
P = fx.SIM_MEASURED


def _amounts(allocs):
    return {a.resident_id: a.amount_cents for a in allocs}


@pytest.mark.parametrize(
    ("fixture", "kwh"),
    [(fx.bill_a, (192, 96, 64, 38)), (fx.bill_b, (180, 60, 40, 20))],
)
def test_fixtures_do_pdf(fixture, kwh):
    bill, esperado = fixture()
    shares = [EnergyShare(r, k * 1000, P) for r, k in zip(fx.TENANTS, kwh, strict=True)]
    allocs = allocate(bill, ROOMS, shares)
    assert _amounts(allocs) == _amounts(esperado)
    for got, exp in zip(
        sorted(allocs, key=lambda a: a.resident_id),
        sorted(esperado, key=lambda a: a.resident_id),
        strict=True,
    ):
        assert (got.fixed_share_cents, got.residual_share_cents, got.individual_cents) == (
            exp.fixed_share_cents,
            exp.residual_share_cents,
            exp.individual_cents,
        )
        assert got.room_id == ROOMS[got.resident_id]


def test_fixture_a_em_euros():
    bill, _ = fx.bill_a()
    shares = [
        EnergyShare(r, k * 1000, P) for r, k in zip(fx.TENANTS, (192, 96, 64, 38), strict=True)
    ]
    nomes = dict(zip(fx.TENANTS, ("ana", "bruno", "carla", "diogo"), strict=True))
    got = {nomes[r]: c for r, c in _amounts(allocate(bill, ROOMS, shares)).items()}
    assert got == {"ana": 4512, "bruno": 2976, "carla": 2464, "diogo": 2048}


def test_fixture_c_arredondamento_maior_resto():
    """100 € por 3 iguais: 33,34 / 33,33 / 33,33; o cêntimo vai para o resident_id menor."""
    bill, esperado = fx.bill_c()
    residents = {fx.ANA: None, fx.BRUNO: None, fx.CARLA: None}
    allocs = allocate(bill, residents, [])
    assert sorted(_amounts(allocs).values()) == sorted(_amounts(esperado).values())
    assert _amounts(allocs)[min(residents)] == 3334


def test_zona_comum_divide_por_igual_e_mostra_linha():
    bill, _ = fx.bill_a()
    shares = [EnergyShare(None, 40_000, P), EnergyShare(fx.ANA, 100_000, P)]
    allocs = {a.resident_id: a for a in allocate(bill, ROOMS, shares)}
    ana = allocs[fx.ANA]
    assert ana.attributed_total_wh == 110_000
    kinds = {line.kind: line for line in ana.breakdown}
    assert kinds[BreakdownKind.room].energy_wh == 100_000
    assert kinds[BreakdownKind.common].energy_wh == 10_000
    assert allocs[fx.BRUNO].attributed_total_wh == 10_000
    # 0,16 €/kWh: 110 kWh = 17,60 €; 10 kWh = 1,60 €
    assert ana.individual_cents == 1760 and allocs[fx.BRUNO].individual_cents == 160


def test_sem_atribuicao_nao_cria_divida():
    """Consumos ambíguos/pendentes ficam no resíduo: todos pagam por igual (como hoje)."""
    bill, _ = fx.bill_a()
    amounts = set(_amounts(allocate(bill, ROOMS, [])).values())
    assert amounts == {3000}


def test_kwh_acima_da_fatura_e_inconsistente():
    bill, _ = fx.bill_a()
    with pytest.raises(BillInconsistentError):
        allocate(bill, ROOMS, [EnergyShare(fx.ANA, bill.total_wh + 1, P)])


def test_morador_fora_do_periodo_e_inconsistente():
    bill, _ = fx.bill_a()
    with pytest.raises(BillInconsistentError):
        allocate(bill, {fx.ANA: None}, [EnergyShare(fx.BRUNO, 1000, P)])


def test_sem_moradores_e_inconsistente():
    bill, _ = fx.bill_a()
    with pytest.raises(BillInconsistentError):
        allocate(bill, {}, [])


def test_proveniencia_separada_e_residuo_estimado():
    bill, _ = fx.bill_a()
    shares = [
        EnergyShare(fx.ANA, 10_000, fx.SIM_MEASURED),
        EnergyShare(fx.ANA, 5_000, fx.SIM_INFERRED),
    ]
    ana = next(a for a in allocate(bill, ROOMS, shares) if a.resident_id == fx.ANA)
    assert {(t.provenance, t.energy_wh) for t in ana.attributed_wh} == {
        (fx.SIM_MEASURED, 10_000),
        (fx.SIM_INFERRED, 5_000),
    }
    residuo = next(line for line in ana.breakdown if line.kind is BreakdownKind.residual_share)
    assert residuo.provenance.simulated and residuo.provenance.kind.value == "estimated"


def test_largest_remainder_empates_para_a_chave_menor():
    assert largest_remainder(10, {"b": 1, "a": 1, "c": 1}) == {"a": 4, "b": 3, "c": 3}
    assert largest_remainder(0, {"a": 0}) == {"a": 0}
    assert largest_remainder(7, {"a": Fraction(1, 3), "b": Fraction(2, 3)}) == {"a": 2, "b": 5}


def test_propriedades_aleatorias():
    """Soma exata, componentes ≥ 0, independente da ordem de entrada; 500 casos (semente fixa)."""
    rng = random.Random(2026)
    for _ in range(500):
        n = rng.randint(1, 6)
        residents = {stable_id("r", str(rng.random())): None for _ in range(n)}
        total = rng.randint(1, 50_000)
        fixed = rng.randint(0, total)
        total_wh = rng.randint(1, 2_000_000)
        bill = replace(fx.bill_a()[0], total_cents=total, fixed_cents=fixed, total_wh=total_wh)
        livre = rng.randint(0, total_wh)
        shares = []
        for _ in range(rng.randint(0, 8)):
            wh = rng.randint(0, livre)
            livre -= wh
            alvo = rng.choice([None, *residents])
            shares.append(EnergyShare(alvo, wh, rng.choice([fx.SIM_MEASURED, fx.SIM_INFERRED])))
        allocs = allocate(bill, residents, shares)
        assert sum(a.amount_cents for a in allocs) == total
        assert all(
            min(a.fixed_share_cents, a.residual_share_cents, a.individual_cents) >= 0
            for a in allocs
        )
        rng_copy = shares[:]
        rng.shuffle(rng_copy)
        assert _amounts(allocate(bill, dict(reversed(residents.items())), rng_copy)) == _amounts(
            allocs
        )


# --- atribuições + consumos → partilhas -------------------------------------------------------


def _attr(event_id, resident=None, status=AttributionStatus.active, n="1"):
    return Attribution(
        id=stable_id("attr", str(event_id), n),
        household_id=fx.HOUSEHOLD,
        consumption_event_id=event_id,
        target_type=AttributionTarget.resident if resident else AttributionTarget.common,
        target_resident_id=resident,
        method=AttributionMethod.manual,
        provenance=fx.SIM_MEASURED,
        decided_by=Audit(at=fx.T0, by_system="billing"),
        status=status,
    )


def test_shares_so_de_atribuicoes_ativas_e_consumos_fechados():
    fechado = fx.consumption(closed=True)
    a_decorrer = replace(fx.consumption(), id=stable_id("consumption", "outro"))
    antiga = _attr(fechado.id, fx.BRUNO, AttributionStatus.superseded, "0")
    atual = _attr(fechado.id, fx.CARLA)
    shares = shares_from_attributions(
        [antiga, atual, _attr(a_decorrer.id)], {fechado.id: fechado, a_decorrer.id: a_decorrer}
    )
    assert shares == [EnergyShare(fx.CARLA, 3000, fechado.provenance)]


def test_shares_rejeitam_duas_ativas_e_consumo_em_falta():
    fechado = fx.consumption(closed=True)
    with pytest.raises(ValueError):
        shares_from_attributions(
            [_attr(fechado.id, fx.BRUNO, n="a"), _attr(fechado.id, fx.CARLA, n="b")],
            {fechado.id: fechado},
        )
    with pytest.raises(BillInconsistentError):
        shares_from_attributions([_attr(fechado.id)], {})


def test_consumo_descartado_nao_entra():
    descartado = replace(
        fx.consumption(closed=True),
        status=ConsumptionStatus.discarded,
        ended_at=fx.T0 + timedelta(minutes=1),
    )
    assert shares_from_attributions([_attr(descartado.id)], {descartado.id: descartado}) == []
