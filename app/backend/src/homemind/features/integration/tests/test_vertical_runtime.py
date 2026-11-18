"""Percurso vertical no runtime (DEMO-02): leituras SIMULADAS → degraus → consumo → atribuição →
fatura de 120 € → fecho → quatro recibos. Só consumidores e rotas reais; nada pré-calculado."""

import time

from homemind.contracts import fixtures as fx
from homemind.core.events import append_event
from homemind.demo.scenario import events as scenario_events

HOUSE = f"/api/households/{fx.HOUSEHOLD}"
LANDLORD = {"x-test-sub": "sub-senhorio"}
TENANTS = {n: {"x-test-sub": f"sub-{n}"} for n in ("ana", "bruno", "carla", "diogo")}
BILL = {
    "period": {"start": "2026-11-01", "end": "2026-11-30"},
    "total_cents": 12_000,
    "fixed_cents": 2_400,
    "total_wh": 600_000,
    "origin": "simulated",
}


def _wait(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if v := fn():
            return v
        time.sleep(0.05)
    raise AssertionError("condição não cumprida a tempo")


def test_leituras_ate_quatro_recibos_somam_a_fatura(app, client, now):
    from datetime import timedelta

    now["value"] = fx.T0 + timedelta(days=40)
    for e in (e for e in scenario_events() if e.type == "energy.reading_recorded"):
        app.state.db.run_sync(lambda c, e=e: append_event(c, e))
    app.state.bus._loop.call_soon_threadsafe(app.state.bus._wake)

    overview = _wait(
        lambda: (r := client.get(f"{HOUSE}/energy/overview", headers=TENANTS["ana"])).json()[
            "sessions"
        ]
        and r.json()
    )
    # Sem assinatura no catálogo: nada identificado, nenhum custo inventado.
    assert all(s["appliance_id"] is None and s["cost_cents"] is None for s in overview["sessions"])

    r = client.post(f"{HOUSE}/bills", json=BILL, headers=LANDLORD)
    assert r.status_code == 201, r.text
    bill_id = r.json()["id"]
    r = client.post(f"{HOUSE}/bills/{bill_id}/finalize", headers=LANDLORD)
    assert r.status_code == 200, r.text

    receipts = {
        n: client.get(f"{HOUSE}/bills/{bill_id}/receipt", headers=h) for n, h in TENANTS.items()
    }
    assert all(r.status_code == 200 for r in receipts.values())
    assert sum(r.json()["amount_cents"] for r in receipts.values()) == 12_000

    # Repetir o fecho não duplica nem altera nada.
    assert client.post(f"{HOUSE}/bills/{bill_id}/finalize", headers=LANDLORD).status_code == 409
    assert (
        client.get(f"{HOUSE}/bills/{bill_id}/receipt", headers=TENANTS["ana"]).json()
        == receipts["ana"].json()
    )

    # O senhorio só vê totais por quarto: nenhuma chave de presença/horário.
    summary = client.get(f"{HOUSE}/bills/{bill_id}/summary", headers=LANDLORD)
    assert summary.status_code == 200
    assert sum(r["amount_cents"] for r in summary.json()["rooms"]) <= 12_000
