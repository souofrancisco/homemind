"""Entrada da fatura (BILL-01). Fatura do PDF (120 € = 24 € fixos + 600 kWh), SIMULADA."""

from datetime import date

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BillIn, BillInconsistentError, BillPeriod
from homemind.contracts.common import Origin
from homemind.features.billing.bills import check_bill
from homemind.features.households.tests.conftest import HOUSE_B

TODAY = date(2026, 12, 5)
NOV = {"start": "2026-11-01", "end": "2026-11-30"}
PDF = {"period": NOV, "total_cents": 12_000, "fixed_cents": 2_400, "total_wh": 600_000}
SIM = {**PDF, "origin": "simulated"}
LANDLORD, ANA, OPERATOR = ({"x-test-sub": s} for s in ("sub-senhorio", "sub-ana", "sub-operador"))
URL = f"/api/households/{fx.HOUSEHOLD}/bills"


def _in(**over):
    return BillIn.model_validate({**SIM, **over})


# --- regras puras -------------------------------------------------------------------------------


def test_fatura_do_pdf_e_valida():
    p = check_bill(_in(price_millicents_per_kwh=16_000), TODAY, real_household=False)
    assert (p.energy_cents, p.price_millicents_per_kwh, p.days) == (9_600, 16_000, 30)


@pytest.mark.parametrize(
    ("over", "motivo"),
    [
        ({"fixed_cents": 12_000}, "parcela fixa"),
        ({"total_wh": 600}, "fora de 0,01"),  # kWh escritos como Wh
        ({"total_cents": 120, "fixed_cents": 24}, "fora de 0,01"),  # euros como cêntimos
        ({"price_millicents_per_kwh": 20_000}, "não fecham"),
        ({"price_millicents_per_kwh": 160}, "tarifa fora"),
        ({"period": {"start": "2026-11-01", "end": "2026-12-31"}}, "ainda não terminou"),
        ({"period": {"start": "2026-08-01", "end": "2026-11-30"}}, "acima de 62"),
    ],
)
def test_valores_que_nao_fecham_sao_recusados(over, motivo):
    with pytest.raises(BillInconsistentError, match=motivo):
        check_bill(_in(**over), TODAY, real_household=False)


def test_tarifa_com_arredondamentos_dentro_da_folga():
    # 600 kWh × 0,1601 € = 96,06 € vs 96,00 €: 6 cêntimos ≤ 1 % → fecha
    check_bill(_in(price_millicents_per_kwh=16_010), TODAY, real_household=False)


def test_fatura_simulada_nunca_numa_casa_real():
    with pytest.raises(BillInconsistentError, match="simulada"):
        check_bill(_in(), TODAY, real_household=True)
    real = BillIn.model_validate({**PDF, "origin": Origin.real})
    check_bill(real, TODAY, real_household=True)


def test_periodo_invertido_e_pedido_invalido():
    with pytest.raises(ValueError):
        BillPeriod(start=date(2026, 11, 30), end=date(2026, 11, 1))


# --- API ----------------------------------------------------------------------------------------


@pytest.fixture
def dezembro(now):
    now["value"] = now["value"].replace(month=12, day=5)


def test_preview_nao_grava(client, dezembro):
    r = client.post(f"{URL}/preview", json=SIM, headers=LANDLORD)
    assert r.status_code == 200, r.text
    assert r.json()["price_millicents_per_kwh"] == 16_000
    assert client.get(URL, headers=LANDLORD).json() == []


def test_senhorio_grava_rascunho_e_emite_evento(app, client, dezembro):
    r = client.post(URL, json=SIM, headers=LANDLORD)
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["status"] == "draft" and bill["revision"] == 1
    assert bill["provenance"] == {"origin": "simulated", "kind": "measured"}
    assert "created_by" not in bill  # sem ids de terceiros
    assert [b["id"] for b in client.get(URL, headers=LANDLORD).json()] == [bill["id"]]
    assert client.get(f"{URL}/{bill['id']}", headers=LANDLORD).status_code == 200
    eventos = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT type, payload_json FROM domain_event WHERE type = 'billing.bill_created'"
        ).fetchall()
    )
    assert len(eventos) == 1 and bill["id"] in eventos[0]["payload_json"]


def test_periodo_sobreposto_e_recusado(client, dezembro):
    assert client.post(URL, json=SIM, headers=LANDLORD).status_code == 201
    meio = {**SIM, "period": {"start": "2026-11-15", "end": "2026-11-30"}}
    r = client.post(URL, json=meio, headers=LANDLORD)
    assert r.status_code == 422 and r.json()["error"]["code"] == "bill_inconsistent"
    assert client.post(f"{URL}/preview", json=meio, headers=LANDLORD).status_code == 422


def test_valores_invalidos_respondem_422_sem_gravar(client, dezembro):
    r = client.post(URL, json={**SIM, "price_millicents_per_kwh": 20_000}, headers=LANDLORD)
    assert r.status_code == 422 and "não fecham" in r.json()["error"]["message"]
    assert client.get(URL, headers=LANDLORD).json() == []


def test_campos_extra_ou_em_falta_sao_400(client, dezembro):
    assert client.post(URL, json={**SIM, "x": 1}, headers=LANDLORD).status_code == 400
    assert client.post(URL, json={"period": NOV}, headers=LANDLORD).status_code == 400


def test_inquilino_nao_grava_nem_ve_rascunhos(client, dezembro):
    assert client.post(URL, json=SIM, headers=ANA).status_code == 403
    bill = client.post(URL, json=SIM, headers=LANDLORD).json()
    assert client.get(URL, headers=ANA).json() == []
    r = client.get(f"{URL}/{bill['id']}", headers=ANA)
    assert r.status_code == 404 and r.json()["error"]["code"] == "bill_not_found"


def test_operador_nao_ve_faturas_e_outra_casa_nao_existe(client, dezembro):
    assert client.get(URL, headers=OPERATOR).status_code == 403
    outra = f"/api/households/{HOUSE_B}/bills"
    assert client.get(outra, headers=LANDLORD).status_code == 404  # não revela a casa


def test_fatura_de_outra_casa_nao_aparece(client, dezembro):
    bill = client.post(URL, json=SIM, headers=LANDLORD).json()
    r = client.get(
        f"/api/households/{HOUSE_B}/bills/{bill['id']}", headers={"x-test-sub": "sub-hugo"}
    )
    assert r.status_code == 404
