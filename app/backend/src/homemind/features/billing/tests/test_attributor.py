"""Atribuidor (BILL-02) sobre a base real em memória e a casa demo. Consumos SIMULADOS."""

import asyncio
import time
from datetime import timedelta

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, AttributionTarget
from homemind.contracts.common import cost_cents, replace, stable_id
from homemind.contracts.energy import ConsumptionStatus, CostEstimate, LocationKind
from homemind.contracts.notification import (
    ConfirmationOutcome,
    ConfirmationVerdict,
    NotificationRef,
    NotificationResponse,
    RefType,
)
from homemind.features.billing import attributor
from homemind.features.billing.router import run_expiry

TS = fx.T0 + timedelta(minutes=30)


def _consumo(wh=5000, closed=True, **over):
    """Aquecedor na sala; 5 kWh = 0,80 € (acima do limiar de 0,50 €)."""
    base = fx.consumption(closed=closed)
    cost = CostEstimate(
        cents=cost_cents(wh, fx.PRICE_MILLICENTS), price_millicents_per_kwh=fx.PRICE_MILLICENTS
    )
    return replace(base, energy_wh=wh, cost_estimate=cost, **over)


def _evento(c, ts=TS):
    cls = (
        de.EnergyConsumptionClosed
        if c.status is ConsumptionStatus.closed
        else (de.EnergyConsumptionDetected)
    )
    return cls(ts=ts, household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c)


def _votacao(verdict, resident=None, voter=fx.CARLA, at=TS + timedelta(minutes=5)):
    return de.NotificationResponded(
        ts=at,
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED,
        data=de.NotificationRespondedData(
            response=NotificationResponse(
                notification_id=fx.NOTIFICATION,
                action_id="mine"
                if verdict is ConfirmationVerdict.self_claimed
                else "other"
                if verdict is ConfirmationVerdict.accusation_accepted
                else "everyone",
                resident_id=voter,
                responded_at=at,
                target_resident_id=resident
                if verdict is ConfirmationVerdict.accusation_accepted
                else None,
            ),
            ref=NotificationRef(type=RefType.consumption_event, id=fx.CONSUMPTION),
            outcome=ConfirmationOutcome(
                verdict=verdict, resident_id=resident, votes=2, votes_needed=2
            ),
        ),
    )


def _handle(app, ev, seq=1):
    return app.state.db.run_sync(lambda c: attributor.handle(c, de.StoredEvent(seq=seq, event=ev)))


def _ativa(app, cid=fx.CONSUMPTION):
    return app.state.db.run_sync(lambda c: attributor.active_attribution(c, cid))


def _pedido(app, cid=fx.CONSUMPTION):
    row = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT status FROM billing_confirmation WHERE consumption_event_id = ?", (str(cid),)
        ).fetchone()
    )
    return row["status"] if row else None


def test_quarto_atribui_ao_morador(app):
    c = _consumo(location=LocationKind.room, room_id=fx.ROOM_ANA)
    [ev] = _handle(app, _evento(c))
    a = _ativa(app)
    assert isinstance(ev, de.BillingAttributionChanged) and ev.data == a
    assert a.target_resident_id == fx.ANA and a.method is AttributionMethod.room_rule


def test_sala_abaixo_do_limiar_vai_para_todos(app):
    _handle(app, _evento(_consumo(wh=1000)))
    a = _ativa(app)
    assert a.target_type is AttributionTarget.common and _pedido(app) is None


def test_sala_acima_do_limiar_pergunta_uma_vez(app):
    [ev] = _handle(app, _evento(_consumo(closed=False)))
    assert isinstance(ev, de.BillingConfirmationNeeded)
    assert ev.data.eligible_resident_ids == sorted(fx.TENANTS)
    assert ev.data.expires_at == TS + timedelta(hours=24)
    assert _pedido(app) == "pending" and _ativa(app) is None
    assert _handle(app, _evento(_consumo(), ts=TS + timedelta(hours=1)), seq=2) == []


def test_votacao_e_minha_atribui_a_quem_assumiu(app):
    _handle(app, _evento(_consumo()))
    [ev] = _handle(app, _votacao(ConfirmationVerdict.self_claimed, fx.CARLA), seq=2)
    a = _ativa(app)
    assert ev.data == a and a.target_resident_id == fx.CARLA
    assert a.method is AttributionMethod.confirmation and a.decided_by.by_resident_id == fx.CARLA
    assert _pedido(app) == "resolved"
    # um voto atrasado já não muda nada
    assert _handle(app, _votacao(ConfirmationVerdict.everyone), seq=3) == []


def test_votacao_aceita_atribuicao_a_outro(app):
    _handle(app, _evento(_consumo()))
    _handle(app, _votacao(ConfirmationVerdict.accusation_accepted, fx.BRUNO), seq=2)
    assert _ativa(app).target_resident_id == fx.BRUNO


def test_votacao_inconclusiva_vai_para_todos(app):
    _handle(app, _evento(_consumo()))
    _handle(app, _votacao(ConfirmationVerdict.everyone), seq=2)
    assert _ativa(app).target_type is AttributionTarget.common


def test_votacao_ainda_a_decorrer_nao_decide(app):
    _handle(app, _evento(_consumo()))
    pendente = _votacao(ConfirmationVerdict.everyone)
    pendente = replace(
        pendente,
        data=replace(
            pendente.data,
            outcome=ConfirmationOutcome(
                verdict=ConfirmationVerdict.pending, votes=1, votes_needed=2
            ),
        ),
    )
    assert _handle(app, pendente, seq=2) == [] and _pedido(app) == "pending"


def test_prazo_esgotado_divide_por_todos(app):
    _handle(app, _evento(_consumo()))
    antes = app.state.db.run_sync(lambda c: attributor.expire_pending(c, TS + timedelta(hours=23)))
    assert antes == [] and _pedido(app) == "pending"
    [ev] = app.state.db.run_sync(lambda c: attributor.expire_pending(c, TS + timedelta(hours=24)))
    a = _ativa(app)
    assert ev.data == a and a.target_type is AttributionTarget.common
    assert a.method is AttributionMethod.equal_fallback and _pedido(app) == "expired"
    assert _handle(app, _votacao(ConfirmationVerdict.self_claimed, fx.CARLA), seq=2) == []


def test_ongoing_atrasado_nao_substitui_o_fecho(app):
    _handle(app, _evento(_consumo(wh=1000)))
    _handle(app, _evento(_consumo(wh=500, closed=False)), seq=2)
    guardado = app.state.db.run_sync(lambda c: attributor.load_consumption(c, fx.CONSUMPTION))
    assert guardado.status is ConsumptionStatus.closed and guardado.energy_wh == 1000


def _ate(fn, timeout=5.0):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if (v := fn()) is not None:
            return v
        time.sleep(0.05)
    raise AssertionError("condição não cumprida a tempo")


def test_ponta_a_ponta_com_barramento_e_notificacoes(app, client, now):
    """Consumo na sala → pedido → notificação (P3) → Carla vota «É minha» → atribuição."""
    now["value"] = TS + timedelta(minutes=1)
    carla = {"x-test-sub": "sub-carla"}
    url = f"/api/households/{fx.HOUSEHOLD}/notifications"
    app.state.bus.publish_threadsafe(_evento(_consumo()))
    [n] = _ate(lambda: client.get(url, headers=carla).json() or None)
    assert n["voting"]["eligible"] == 4
    r = client.post(f"{url}/{n['id']}/respond", json={"action_id": "mine"}, headers=carla)
    assert r.status_code == 200, r.text
    a = _ate(lambda: _ativa(app))
    assert a.target_resident_id == fx.CARLA and a.method is AttributionMethod.confirmation


def test_run_expiry_grava_e_publica(app):
    _handle(app, _evento(_consumo()))
    publicados = []

    class Bus:
        async def publish(self, e):
            publicados.append(e)

    n = asyncio.run(run_expiry(app.state.db, Bus(), TS + timedelta(days=2)))
    esperado = stable_id(
        "billing.attribution_changed", str(stable_id("attribution", str(fx.CONSUMPTION), "expired"))
    )
    gravados = app.state.db.run_sync(
        lambda c: [
            r["id"]
            for r in c.execute(
                "SELECT id FROM domain_event WHERE type = 'billing.attribution_changed'"
            )
        ]
    )
    assert n == 1 and [e.id for e in publicados] == [esperado] and gravados == [str(esperado)]
