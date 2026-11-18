"""Primeira decisão de atribuição (BILL-02) com consumos SIMULADOS das fixtures."""

from datetime import timedelta

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, AttributionTarget
from homemind.contracts.common import ValueKind, cost_cents, replace
from homemind.contracts.energy import ConsumptionStatus, CostEstimate, LocationKind
from homemind.contracts.household import CommonAreaRule, HouseholdPolicy
from homemind.features.billing.attribution import decide, worth_asking

NOW = fx.T0 + timedelta(hours=2)
ROOM_RESIDENT = {fx.ROOM_ANA: fx.ANA, fx.ROOM_BRUNO: fx.BRUNO}
POLICY = HouseholdPolicy()  # ask, 0,50 €, 24 h


def _custo(event, cents):
    """Energia que custa `cents` a 0,16 €/kWh (o contrato exige custo coerente com a energia)."""
    wh = cents * 1000 * 1000 // fx.PRICE_MILLICENTS
    assert cost_cents(wh, fx.PRICE_MILLICENTS) == cents
    return replace(
        event,
        energy_wh=wh,
        cost_estimate=CostEstimate(cents=cents, price_millicents_per_kwh=fx.PRICE_MILLICENTS),
    )


def _no_quarto(event, room):
    return replace(event, location=LocationKind.room, room_id=room)


def test_quarto_e_do_morador_mesmo_com_aparelho_de_outro():
    """«O teu quarto é teu»: o aquecedor do Bruno no quarto da Ana é da Ana."""
    d = decide(
        _no_quarto(fx.consumption(closed=True), fx.ROOM_ANA), POLICY, ROOM_RESIDENT, fx.TENANTS, NOW
    )
    a = d.attribution
    assert d.confirmation is None
    assert a.target_type is AttributionTarget.resident and a.target_resident_id == fx.ANA
    assert a.method is AttributionMethod.room_rule
    assert a.provenance.simulated and a.provenance.kind is ValueKind.measured
    assert a.decided_by.by_system == "billing"


def test_quarto_sem_morador_vai_para_a_conta_comum():
    d = decide(
        _no_quarto(fx.consumption(closed=True), fx.ROOM_CARLA),
        POLICY,
        ROOM_RESIDENT,
        fx.TENANTS,
        NOW,
    )
    assert d.attribution.target_type is AttributionTarget.common
    assert d.attribution.method is AttributionMethod.equal_fallback


def test_zona_comum_acima_do_limiar_pergunta():
    event = _custo(fx.consumption(closed=True), 50)
    d = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.attribution is None
    c = d.confirmation
    assert c.consumption_event_id == event.id and c.estimated_cost_cents == 50
    assert c.eligible_resident_ids == list(fx.TENANTS)
    assert c.expires_at == NOW + timedelta(hours=24)


def test_pedido_de_confirmacao_inclui_nome_do_aparelho():
    event = _custo(fx.consumption(closed=True), 50)
    d = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW, appliance_name="Aquecedor")
    assert d.confirmation.appliance_name == "Aquecedor"


def test_pedido_de_confirmacao_sem_nome_deixa_nome_vazio():
    event = _custo(fx.consumption(closed=True), 50)
    d = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.confirmation.appliance_name is None


def test_pergunta_mesmo_a_decorrer_quando_ja_passou_o_limiar():
    d = decide(_custo(fx.consumption(), 80), POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.confirmation is not None


def test_zona_comum_abaixo_do_limiar_divide_por_igual():
    d = decide(_custo(fx.consumption(closed=True), 49), POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.confirmation is None
    assert d.attribution.target_type is AttributionTarget.common


def test_a_decorrer_abaixo_do_limiar_espera_pelo_fecho():
    d = decide(_custo(fx.consumption(), 10), POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.attribution is None and d.confirmation is None


def test_sem_custo_estimavel_nao_pergunta():
    event = replace(fx.consumption(closed=True), cost_estimate=None)
    assert not worth_asking(event, POLICY)
    assert decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW).attribution.target_type is (
        AttributionTarget.common
    )


def test_localizacao_desconhecida_nao_assume_quarto():
    event = _custo(
        replace(fx.consumption(closed=True), location=LocationKind.unknown, room_id=None), 10
    )
    d = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.attribution.target_type is AttributionTarget.common


def test_regra_igual_nunca_pergunta():
    policy = HouseholdPolicy(common_area_rule=CommonAreaRule.equal)
    d = decide(_custo(fx.consumption(closed=True), 5000), policy, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.confirmation is None and d.attribution.target_type is AttributionTarget.common


def test_limiar_configuravel():
    policy = HouseholdPolicy(ask_threshold_cents=200, ask_timeout_hours=12)
    assert (
        decide(
            _custo(fx.consumption(closed=True), 150), policy, ROOM_RESIDENT, fx.TENANTS, NOW
        ).confirmation
        is None
    )
    c = decide(
        _custo(fx.consumption(closed=True), 200), policy, ROOM_RESIDENT, fx.TENANTS, NOW
    ).confirmation
    assert c.expires_at == NOW + timedelta(hours=12)


def test_descartado_nao_decide_nada():
    event = replace(
        fx.consumption(closed=True),
        status=ConsumptionStatus.discarded,
        ended_at=fx.T0 + timedelta(minutes=1),
    )
    d = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert d.attribution is None and d.confirmation is None


def test_decisao_deterministica():
    event = fx.consumption(closed=True)
    a = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    b = decide(event, POLICY, ROOM_RESIDENT, fx.TENANTS, NOW)
    assert a == b
