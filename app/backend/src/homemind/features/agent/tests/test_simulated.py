"""Providers SIMULADOS: os valores são os das fixtures, só para a casa e o período da demo."""

from uuid import uuid4

import pytest

from homemind.contracts import fixtures as fx
from homemind.features.agent.simulated import EmptyProviders, SimulatedProviders

PERIOD = "2026-11"


@pytest.fixture
def sim():
    return SimulatedProviders()


def _alloc(resident):
    return {a.resident_id: a for a in fx.bill_a()[1]}[resident]


def test_consumo_e_a_alocacao_do_residente(sim):
    alloc = _alloc(fx.ANA)
    v = sim.consumption_summary(fx.HOUSEHOLD, fx.ANA, PERIOD)
    assert v.energy_wh == alloc.attributed_total_wh
    assert v.cost_cents == alloc.individual_cents
    assert v.provenance == fx.SIM_INFERRED and v.provenance.simulated


def test_cada_residente_tem_o_seu_consumo(sim):
    values = {r: sim.consumption_summary(fx.HOUSEHOLD, r, PERIOD).energy_wh for r in fx.TENANTS}
    assert values == {r: _alloc(r).attributed_total_wh for r in fx.TENANTS}


def test_recibo_e_o_total_da_alocacao(sim):
    bill_id, period = sim.latest_bill(fx.HOUSEHOLD, fx.ANA)
    assert (bill_id, period) == (fx.BILL_A, PERIOD)
    v = sim.receipt(fx.HOUSEHOLD, fx.ANA, bill_id)
    assert v.cost_cents == _alloc(fx.ANA).amount_cents
    assert v.provenance.simulated


def test_orcamento_so_da_carla_e_do_mes_do_orcamento(sim):
    budget = fx.budget()
    v = sim.budget_status(fx.HOUSEHOLD, budget.resident_id, budget.period)
    assert v is not None and v.cost_cents is not None and v.provenance.simulated
    assert sim.budget_status(fx.HOUSEHOLD, fx.ANA, budget.period) is None  # orçamento de outra
    assert sim.budget_status(fx.HOUSEHOLD, budget.resident_id, "2026-10") is None


def test_outra_casa_outro_periodo_ou_outro_residente_sem_dados(sim):
    other = uuid4()
    assert sim.consumption_summary(other, fx.ANA, PERIOD) is None
    assert sim.consumption_summary(fx.HOUSEHOLD, fx.ANA, "2026-10") is None
    assert sim.consumption_summary(fx.HOUSEHOLD, fx.LANDLORD, PERIOD) is None
    assert sim.consumption_summary(fx.HOUSEHOLD, other, PERIOD) is None
    assert sim.budget_status(other, fx.CARLA, fx.budget().period) is None
    assert sim.latest_bill(other, fx.ANA) is None
    assert sim.latest_bill(fx.HOUSEHOLD, other) is None
    assert sim.receipt(other, fx.ANA, fx.BILL_A) is None
    assert sim.receipt(fx.HOUSEHOLD, fx.ANA, fx.BILL_B) is None  # outra fatura


def test_vazio_nunca_tem_dados():
    e = EmptyProviders()
    assert e.consumption_summary(fx.HOUSEHOLD, fx.ANA, PERIOD) is None
    assert e.budget_status(fx.HOUSEHOLD, fx.CARLA, PERIOD) is None
    assert e.latest_bill(fx.HOUSEHOLD, fx.ANA) is None
    assert e.receipt(fx.HOUSEHOLD, fx.ANA, fx.BILL_A) is None
