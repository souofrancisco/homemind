"""Fecho do mês (BILL-04): fatura do PDF (120 €) e consumos da casa demo, tudo SIMULADO."""

from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import cost_cents, replace, stable_id
from homemind.contracts.energy import CostEstimate, LocationKind
from homemind.features.billing import attributor

SIM = {
    "period": {"start": "2026-11-01", "end": "2026-11-30"},
    "total_cents": 12_000,
    "fixed_cents": 2_400,
    "total_wh": 600_000,
    "origin": "simulated",
}
LANDLORD, ANA, BRUNO, OPERATOR = (
    {"x-test-sub": s} for s in ("sub-senhorio", "sub-ana", "sub-bruno", "sub-operador")
)
URL = f"/api/households/{fx.HOUSEHOLD}/bills"


@pytest.fixture(autouse=True)
def dezembro(now):
    now["value"] = now["value"].replace(month=12, day=5)


def _consumo(app, nome, wh, started=fx.T0, **over):
    """Consumo fechado SIMULADO, passado pelo atribuidor (como viria do barramento)."""
    base = fx.consumption(closed=True)
    c = replace(
        base,
        id=stable_id("consumption", nome),
        energy_wh=wh,
        started_at=started,
        ended_at=started + timedelta(hours=1),
        cost_estimate=CostEstimate(
            cents=cost_cents(wh, fx.PRICE_MILLICENTS), price_millicents_per_kwh=fx.PRICE_MILLICENTS
        ),
        **over,
    )
    ev = de.EnergyConsumptionClosed(
        ts=started + timedelta(hours=1), household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c
    )
    app.state.db.run_sync(lambda conn: attributor.handle(conn, de.StoredEvent(seq=1, event=ev)))
    return c


def _no_quarto(room):
    return {"location": LocationKind.room, "room_id": room}


def _rascunho(client, body=SIM):
    r = client.post(URL, json=body, headers=LANDLORD)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fechar(client, bill_id):
    return client.post(f"{URL}/{bill_id}/finalize", headers=LANDLORD)


def _recibo(client, bill_id, who):
    r = client.get(f"{URL}/{bill_id}/receipt", headers=who)
    assert r.status_code == 200, r.text
    return r.json()


def test_sem_consumos_divide_por_igual(client):
    bill = _rascunho(client)
    r = _fechar(client, bill)
    assert r.status_code == 200 and r.json()["status"] == "finalized"
    assert _recibo(client, bill, ANA)["amount_cents"] == 3000


def test_quarto_e_sala_somam_o_total_ao_centimo(app, client):
    _consumo(app, "ana-quarto", 100_000, **_no_quarto(fx.ROOM_ANA))  # 100 kWh no quarto da Ana
    _consumo(app, "chaleira", 2_000)  # sala, abaixo do limiar → conta comum (0,5 kWh cada)
    bill = _rascunho(client)
    assert _fechar(client, bill).status_code == 200
    ana, bruno = _recibo(client, bill, ANA), _recibo(client, bill, BRUNO)
    assert ana["attributed_wh"][0]["energy_wh"] == 100_500 and ana["individual_cents"] == 1608
    assert bruno["individual_cents"] == 8
    resumo = client.get(f"{URL}/{bill}/summary", headers=LANDLORD).json()
    assert sum(q["amount_cents"] for q in resumo["rooms"]) == 12_000
    nomes = {q["room_name"] for q in resumo["rooms"]}
    assert nomes == {"Quarto Ana", "Quarto Bruno", "Quarto Carla", "Quarto Diogo"}


def test_consumo_fora_do_periodo_nao_entra(app, client):
    _consumo(app, "outubro", 100_000, started=fx.T0 - timedelta(days=40), **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    _fechar(client, bill)
    assert _recibo(client, bill, ANA)["amount_cents"] == 3000


def test_pergunta_pendente_nao_cria_divida_e_expirada_vai_para_todos(app, client):
    _consumo(app, "aquecedor", 10_000)  # 1,60 € na sala → pergunta (24 h a partir de T0+1h)
    bill = _rascunho(client)
    _fechar(client, bill)  # 5/12: o prazo já passou → por todos (2,5 kWh cada)
    assert _recibo(client, bill, ANA)["attributed_wh"][0]["energy_wh"] == 2_500
    estado = app.state.db.run_sync(
        lambda c: c.execute("SELECT status FROM billing_confirmation").fetchone()["status"]
    )
    assert estado == "expired"


def test_fechar_duas_vezes_e_409_e_nao_duplica(app, client):
    bill = _rascunho(client)
    assert _fechar(client, bill).status_code == 200
    r = _fechar(client, bill)
    assert r.status_code == 409 and r.json()["error"]["code"] == "bill_finalized"
    n = app.state.db.run_sync(
        lambda c: (
            c.execute("SELECT count(*) FROM billing_allocation").fetchone()[0],
            c.execute(
                "SELECT count(*) FROM domain_event WHERE type = 'billing.bill_finalized'"
            ).fetchone()[0],
            c.execute(
                "SELECT count(*) FROM domain_event WHERE type = 'billing.allocation_published'"
            ).fetchone()[0],
        )
    )
    assert n == (4, 1, 4)


def test_kwh_atribuidos_acima_da_fatura_e_422_sem_fechar(app, client):
    _consumo(app, "enorme", 700_000, **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    r = _fechar(client, bill)
    assert r.status_code == 422 and r.json()["error"]["code"] == "bill_inconsistent"
    assert client.get(f"{URL}/{bill}", headers=LANDLORD).json()["status"] == "draft"


def test_correcao_cria_revisao_e_guarda_a_anterior(app, client):
    bill = _rascunho(client)
    _fechar(client, bill)
    corrigida = {**SIM, "total_cents": 12_400}
    r = client.post(f"{URL}/{bill}/revisions", json=corrigida, headers=LANDLORD)
    assert r.status_code == 201, r.text
    nova = r.json()
    assert (nova["revision"], nova["status"], nova["total_cents"]) == (2, "finalized", 12_400)
    assert client.get(f"{URL}/{bill}", headers=LANDLORD).json()["status"] == "superseded"
    assert _recibo(client, bill, ANA)["amount_cents"] == 3000  # o antigo continua legível
    assert _recibo(client, nova["id"], ANA)["amount_cents"] == 3100
    estados = sorted(b["status"] for b in client.get(URL, headers=ANA).json())
    assert estados == ["finalized", "superseded"]


def test_so_se_corrige_uma_fatura_fechada(client):
    bill = _rascunho(client)
    r = client.post(f"{URL}/{bill}/revisions", json=SIM, headers=LANDLORD)
    assert r.status_code == 409 and r.json()["error"]["code"] == "bill_not_finalized"


def test_correcao_invalida_nao_mexe_na_original(client):
    bill = _rascunho(client)
    _fechar(client, bill)
    r = client.post(
        f"{URL}/{bill}/revisions", json={**SIM, "fixed_cents": 12_000}, headers=LANDLORD
    )
    assert r.status_code == 422
    assert client.get(f"{URL}/{bill}", headers=LANDLORD).json()["status"] == "finalized"


def test_permissoes_do_fecho_e_dos_recibos(client):
    bill = _rascunho(client)
    assert client.post(f"{URL}/{bill}/finalize", headers=ANA).status_code == 403
    assert client.get(f"{URL}/{bill}/receipt", headers=ANA).status_code == 404  # rascunho
    _fechar(client, bill)
    assert client.get(f"{URL}/{bill}/summary", headers=ANA).status_code == 403
    assert client.get(f"{URL}/{bill}/receipt", headers=LANDLORD).status_code == 403
    assert client.get(f"{URL}/{bill}/receipt", headers=OPERATOR).status_code == 403
    recibo = _recibo(client, bill, ANA)
    assert recibo["resident_id"] != str(fx.BRUNO)
    resumo = client.get(f"{URL}/{bill}/summary", headers=LANDLORD).text
    assert str(fx.ANA) not in resumo  # o senhorio vê quartos, não pessoas


def test_fatura_inexistente_e_404(client):
    r = client.post(f"{URL}/{stable_id('x')}/finalize", headers=LANDLORD)
    assert r.status_code == 404 and r.json()["error"]["code"] == "bill_not_found"
