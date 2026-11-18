"""Contestar, corrigir e reemitir (BILL-06): fatura do PDF (120 €) e casa demo, tudo SIMULADO.

Ana tem 100 kWh no quarto (16,00 €): parcela 42,00 € (6 € fixa + 20 € resíduo + 16 €); os
outros 26,00 €. Se esse consumo passar para a conta comum, todos pagam 30,00 €."""

import time
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import cost_cents, replace, stable_id
from homemind.contracts.energy import CostEstimate, LocationKind
from homemind.features.billing import attributor
from homemind.features.notifications.text import format_eur

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
H = f"/api/households/{fx.HOUSEHOLD}"
CONSUMO = stable_id("consumption", "ana-quarto")


@pytest.fixture(autouse=True)
def dezembro(now):
    now["value"] = now["value"].replace(month=12, day=5)


@pytest.fixture
def fatura(app, client):
    """Consumo da Ana no quarto + fatura de novembro fechada. Devolve o id da fatura."""
    c = replace(
        fx.consumption(closed=True),
        id=CONSUMO,
        energy_wh=100_000,
        started_at=fx.T0,
        ended_at=fx.T0 + timedelta(hours=1),
        location=LocationKind.room,
        room_id=fx.ROOM_ANA,
        cost_estimate=CostEstimate(
            cents=cost_cents(100_000, fx.PRICE_MILLICENTS),
            price_millicents_per_kwh=fx.PRICE_MILLICENTS,
        ),
    )
    ev = de.EnergyConsumptionClosed(
        ts=fx.T0 + timedelta(hours=1), household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c
    )
    app.state.db.run_sync(lambda conn: attributor.handle(conn, de.StoredEvent(seq=1, event=ev)))
    bill = client.post(f"{H}/bills", json=SIM, headers=LANDLORD).json()["id"]
    assert client.post(f"{H}/bills/{bill}/finalize", headers=LANDLORD).status_code == 200
    return bill


def _recibo(client, bill, who=ANA):
    r = client.get(f"{H}/bills/{bill}/receipt", headers=who)
    assert r.status_code == 200, r.text
    return r.json()["amount_cents"]


def _contestar(client, bill, who=ANA, **body):
    return client.post(
        f"{H}/bills/{bill}/contestations", json={"reason": "Não é meu.", **body}, headers=who
    )


def _decidir(client, cid, status="accepted", who=LANDLORD, **body):
    return client.post(
        f"{H}/contestations/{cid}/decision",
        json={"status": status, "resolution": "Verifiquei a fatura.", **body},
        headers=who,
    )


def _avisos(client, who, titulo):
    fim = time.monotonic() + 5
    while time.monotonic() < fim:
        found = [
            n for n in client.get(f"{H}/notifications", headers=who).json() if n["title"] == titulo
        ]
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"sem aviso «{titulo}»")


def test_aceitar_passa_o_consumo_para_a_conta_comum_e_reemite(client, fatura):
    assert _recibo(client, fatura) == 4200 and _recibo(client, fatura, BRUNO) == 2600
    r = _contestar(client, fatura, consumption_event_id=str(CONSUMO))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "open" and c["consumption_event_id"] == str(CONSUMO)

    r = _decidir(client, c["id"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "accepted" and (d["before_cents"], d["after_cents"]) == (4200, 3000)
    # a resposta ao senhorio é a vista dele: quarto, nunca o consumo nem o morador
    assert d["room_name"] == "Quarto Ana" and d["contests_consumption"] is True
    assert str(CONSUMO) not in r.text and str(fx.ANA) not in r.text
    nova = d["revision_bill_id"]
    assert client.get(f"{H}/bills/{fatura}", headers=LANDLORD).json()["status"] == "superseded"
    assert client.get(f"{H}/bills/{nova}", headers=LANDLORD).json()["revision"] == 2
    assert _recibo(client, fatura) == 4200  # a original continua legível, intacta
    assert [_recibo(client, nova, w) for w in (ANA, BRUNO)] == [3000, 3000]

    [aviso] = _avisos(client, ANA, "Contestação aceite")
    assert format_eur(4200) in aviso["body"] and format_eur(3000) in aviso["body"]
    assert "Verifiquei a fatura." in aviso["body"] and "SIMULADO" in aviso["body"]


def test_senhorio_ve_quarto_e_motivo_mas_nunca_o_consumo(client, fatura):
    cid = _contestar(client, fatura, consumption_event_id=str(CONSUMO)).json()["id"]
    [aviso] = _avisos(client, LANDLORD, "Nova contestação de um recibo")
    assert "Não é meu." not in aviso["body"]  # o motivo fica na lista, não no aviso
    r = client.get(f"{H}/contestations", headers=LANDLORD)
    assert r.status_code == 200
    [v] = r.json()
    assert (v["id"], v["room_name"], v["reason"], v["contests_consumption"]) == (
        cid, "Quarto Ana", "Não é meu.", True
    )  # fmt: skip
    assert str(CONSUMO) not in r.text and str(fx.ANA) not in r.text
    bruno = client.get(f"{H}/notifications", headers=BRUNO).json()
    assert not [n for n in bruno if "ontestação" in n["title"]]


def test_rejeitar_nao_mexe_na_fatura_e_nao_se_decide_duas_vezes(client, fatura):
    cid = _contestar(client, fatura).json()["id"]
    d = _decidir(client, cid, status="rejected").json()
    assert d["status"] == "rejected" and d["revision_bill_id"] is None
    assert (d["before_cents"], d["after_cents"]) == (4200, 4200)
    assert client.get(f"{H}/bills/{fatura}", headers=LANDLORD).json()["status"] == "finalized"
    r = _decidir(client, cid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "contestation_resolved"
    _avisos(client, ANA, "Contestação rejeitada")
    # rejeitada: pode voltar a contestar
    assert _contestar(client, fatura).status_code == 201


def test_aceitar_com_correcao_dos_dados_da_fatura(client, fatura):
    cid = _contestar(client, fatura).json()["id"]  # sem consumo: o total estava errado
    r = _decidir(client, cid, bill={**SIM, "total_cents": 12_400})
    assert r.status_code == 200, r.text
    assert r.json()["after_cents"] == 4350  # quarto 16,67 + resíduo 20,83 + fixa 6
    bad = _contestar(client, r.json()["revision_bill_id"]).json()["id"]
    r = _decidir(client, bad, bill={**SIM, "fixed_cents": 12_000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bill_inconsistent"
    r = _decidir(client, bad, status="rejected", bill=SIM)
    assert r.status_code == 400  # só se corrige a fatura ao aceitar


def test_correcao_direta_leva_as_contestacoes_abertas_para_a_nova_revisao(client, fatura):
    cid = _contestar(client, fatura, consumption_event_id=str(CONSUMO)).json()["id"]
    nova = client.post(
        f"{H}/bills/{fatura}/revisions", json={**SIM, "total_cents": 12_400}, headers=LANDLORD
    ).json()["id"]
    [mine] = client.get(f"{H}/contestations/mine", headers=ANA).json()
    assert (mine["id"], mine["bill_id"], mine["status"]) == (cid, nova, "open")
    d = _decidir(client, cid).json()
    assert d["before_cents"] == 4350 and d["after_cents"] == 3100
    terceira = client.get(f"{H}/bills/{d['revision_bill_id']}", headers=LANDLORD).json()
    assert terceira["revision"] == 3 and terceira["total_cents"] == 12_400


def test_regras_de_quem_contesta_o_que(client, fatura):
    # Bruno não pode contestar um consumo da Ana
    r = _contestar(client, fatura, who=BRUNO, consumption_event_id=str(CONSUMO))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert _contestar(client, fatura).status_code == 201
    r = _contestar(client, fatura)
    assert r.status_code == 409 and r.json()["error"]["code"] == "contestation_open"
    assert _contestar(client, fatura, who=LANDLORD).status_code == 403
    assert _contestar(client, fatura, who=OPERATOR).status_code == 403
    assert (
        client.post(
            f"{H}/bills/{fatura}/contestations", json={"reason": ""}, headers=BRUNO
        ).status_code
        == 400
    )  # noqa: E501
    # só vê as suas; a lista da casa é do senhorio
    assert client.get(f"{H}/contestations/mine", headers=BRUNO).json() == []
    assert client.get(f"{H}/contestations", headers=ANA).status_code == 403
    assert client.get(f"{H}/contestations/mine", headers=LANDLORD).status_code == 403


def test_decisao_so_do_senhorio_e_estados_da_fatura(client, fatura):
    cid = _contestar(client, fatura).json()["id"]
    assert _decidir(client, cid, who=ANA).status_code == 403
    r = _decidir(client, stable_id("nope"))
    assert r.status_code == 404 and r.json()["error"]["code"] == "contestation_not_found"
    nova = _decidir(client, cid).json()["revision_bill_id"]
    r = _contestar(client, fatura)  # a original foi substituída
    assert r.status_code == 409 and r.json()["error"]["code"] == "bill_not_finalized"
    assert _contestar(client, nova).status_code == 201
    rascunho = client.post(
        f"{H}/bills", json={**SIM, "period": {"start": "2026-12-01", "end": "2026-12-04"}},
        headers=LANDLORD,
    ).json()["id"]  # fmt: skip
    assert _contestar(client, rascunho).status_code == 404
