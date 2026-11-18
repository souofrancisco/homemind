"""Orçamento mensal e avisos 50/80/100 % (ALERT-01). Casa demo e consumos SIMULADOS.

Relógio: 17/11/2026 (conftest). Preço de referência da casa demo: 0,16 €/kWh."""

import time
from datetime import timedelta

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import Budget
from homemind.contracts.common import cost_cents, replace, stable_id
from homemind.contracts.energy import CostEstimate, LocationKind
from homemind.features.billing import attributor, budgets

ANA, LANDLORD, OPERATOR = ({"x-test-sub": s} for s in ("sub-ana", "sub-senhorio", "sub-operador"))
H = f"/api/households/{fx.HOUSEHOLD}"
ME = f"{H}/budgets/me"


def _consumo(app, nome, wh, room=fx.ROOM_ANA, started=fx.T0 - timedelta(days=2)):
    c = replace(
        fx.consumption(closed=True),
        id=stable_id("consumption", nome),
        energy_wh=wh,
        started_at=started,
        ended_at=started + timedelta(hours=1),
        location=LocationKind.room if room else LocationKind.common,
        room_id=room or fx.ROOM_SALA,
        cost_estimate=CostEstimate(
            cents=cost_cents(wh, fx.PRICE_MILLICENTS), price_millicents_per_kwh=fx.PRICE_MILLICENTS
        ),
    )
    ev = de.EnergyConsumptionClosed(
        ts=started + timedelta(hours=1), household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c
    )
    app.state.db.run_sync(lambda conn: attributor.handle(conn, de.StoredEvent(seq=1, event=ev)))


def _avaliar(app, now=fx.T0):
    return app.state.db.run_sync(lambda c: budgets.evaluate(c, fx.HOUSEHOLD, "2026-11", now))


def _definir(client, euros, **extra):
    r = client.put(ME, json={"limit_cents": euros * 100, **extra}, headers=ANA)
    assert r.status_code == 200, r.text
    return r.json()


def test_sem_orcamento_mostra_gasto_e_sem_consumo_e_zero_real(client):
    s = client.get(ME, headers=ANA).json()
    assert s["period"] == "2026-11" and s["budget"] is None
    assert (s["spent_cents"], s["base_cents"], s["pct"]) == (0, None, None)
    assert s["provenance"]["kind"] == "estimated" and s["final"] is False


def test_sem_preco_o_gasto_e_desconhecido_nunca_zero(app, client):
    app.state.db.run_sync(
        lambda c: c.execute("UPDATE household SET energy_price_millicents_per_kwh = NULL")
    )
    _consumo(app, "ana", 10_000)
    s = _definir(client, 25)
    assert s["spent_cents"] is None and s["pct"] is None and s["provenance"] is None
    assert _avaliar(app) == []  # sem números não há aviso


def test_consumo_proprio_e_parte_da_conta_comum(app, client):
    _consumo(app, "ana", 100_000)  # 100 kWh no quarto da Ana = 16,00 €
    _consumo(app, "chaleira", 2_000, room=None)  # sala, abaixo do limiar: 0,5 kWh cada = 0,08 €
    s = _definir(client, 25)
    assert (s["confirmed_cents"], s["shared_cents"], s["spent_cents"]) == (1600, 8, 1608)
    assert s["pct"] == 64


def test_um_aviso_por_limiar_e_salta_para_o_mais_alto(app, client):
    _definir(client, 25)
    _consumo(app, "a", 140_000)  # 22,40 € = 89 %: passa 50 e 80 de uma vez → só o 80
    [ev] = _avaliar(app)
    assert isinstance(ev, de.AlertsThresholdCrossed)
    assert (ev.data.pct, ev.data.spent_cents, ev.data.limit_cents) == (80, 2240, 2500)
    assert ev.data.resident_id == fx.ANA and ev.provenance.simulated
    assert _avaliar(app) == []  # o mesmo limiar nunca duas vezes
    _consumo(app, "b", 20_000)  # +3,20 € = 102 %
    [ev100] = _avaliar(app)
    assert ev100.data.pct == 100 and _avaliar(app) == []


def test_redefinir_e_reset_explicito(app, client):
    _consumo(app, "a", 100_000)  # 16 €
    _definir(client, 25)  # 64 % → avisa 50 já no PUT
    first = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT id FROM domain_event WHERE type = 'alerts.threshold_crossed'"
        ).fetchall()
    )
    assert len(first) == 1
    s = _definir(client, 20)  # reset: 80 % → avisa 80 (novo ciclo, id novo)
    assert s["budget"]["last_threshold_notified"] == 80
    ids = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT count(*) FROM domain_event WHERE type = 'alerts.threshold_crossed'"
        ).fetchone()[0]
    )
    assert ids == 2


def test_base_estimada_pela_fatura_anterior(app, client, now):
    # Outubro fechado: 120 € sem consumos atribuídos → 30 € cada (6 € fixa + 24 € resíduo).
    outubro = {
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    bill = client.post(f"{H}/bills", json=outubro, headers=LANDLORD).json()["id"]
    assert client.post(f"{H}/bills/{bill}/finalize", headers=LANDLORD).status_code == 200
    s = client.get(ME, headers=ANA).json()
    assert s["base_cents"] == round(3000 * 17 / 31)  # 17 dias de novembro passados
    assert s["spent_cents"] == s["base_cents"]


def test_fatura_do_mes_fechada_mostra_o_valor_real(app, client, now):
    _consumo(app, "ana", 100_000)
    now["value"] = now["value"].replace(month=12, day=5)
    nov = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    bill = client.post(f"{H}/bills", json=nov, headers=LANDLORD).json()["id"]
    client.post(f"{H}/bills/{bill}/finalize", headers=LANDLORD)
    recibo = client.get(f"{H}/bills/{bill}/receipt", headers=ANA).json()
    s = client.get(ME, params={"period": "2026-11"}, headers=ANA).json()
    assert s["final"] is True and s["spent_cents"] == recibo["amount_cents"]
    assert s["provenance"]["kind"] == "measured"


def test_aviso_chega_as_notificacoes_da_ana(app, client):
    """Ponta a ponta: consumo no barramento → atribuição → orçamento → aviso pessoal (P3)."""
    _definir(client, 10)
    c = replace(
        fx.consumption(closed=True),
        id=stable_id("consumption", "e2e"),
        energy_wh=50_000,  # 8 € de 10 € = 80 %
        location=LocationKind.room,
        room_id=fx.ROOM_ANA,
        started_at=fx.T0 - timedelta(days=1),
        ended_at=fx.T0 - timedelta(days=1) + timedelta(hours=1),
        cost_estimate=CostEstimate(cents=800, price_millicents_per_kwh=fx.PRICE_MILLICENTS),
    )
    app.state.bus.publish_threadsafe(
        de.EnergyConsumptionClosed(
            ts=fx.T0 - timedelta(days=1), household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c
        )
    )
    fim = time.monotonic() + 5
    while time.monotonic() < fim:
        avisos = [
            n
            for n in client.get(f"{H}/notifications", headers=ANA).json()
            if n["kind"] == "budget_alert"
        ]
        if avisos:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("o aviso de orçamento não chegou")
    [aviso] = avisos
    assert aviso["title"] == "Orçamento a 80 %" and "SIMULADO" in aviso["body"]
    bruno = client.get(f"{H}/notifications", headers={"x-test-sub": "sub-bruno"}).json()
    assert not [n for n in bruno if n["kind"] == "budget_alert"]  # é pessoal


def test_permissoes_e_validacao(client):
    assert client.get(ME, headers=LANDLORD).status_code == 403
    assert client.get(ME, headers=OPERATOR).status_code == 403
    assert client.put(ME, json={"limit_cents": 1000}, headers=LANDLORD).status_code == 403
    r = client.put(ME, json={"limit_cents": 1000, "period": "2026-10"}, headers=ANA)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert client.put(ME, json={"limit_cents": 0}, headers=ANA).status_code == 400
    assert (
        client.put(ME, json={"limit_cents": 1000, "thresholds": [80, 50]}, headers=ANA).status_code
        == 400
    )
    assert client.get(ME, params={"period": "2026-13"}, headers=ANA).status_code == 400


def test_limiar_a_avisar():
    b = Budget(
        id=stable_id("b"), household_id=fx.HOUSEHOLD, kind="personal", resident_id=fx.ANA,
        period="2026-11", limit_cents=1000,
    )  # fmt: skip
    assert [budgets.threshold_to_notify(b, p) for p in (0, 49, 50, 79, 85, 150)] == [
        None, None, 50, 50, 80, 100,
    ]  # fmt: skip
    assert budgets.threshold_to_notify(replace(b, last_threshold_notified=80), 85) is None
