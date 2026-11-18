"""Tarifário simples/bi-horário e previsão do fim do mês (ALERT-02). Tudo SIMULADO.

Casa demo em Europe/Lisbon (UTC+0 em novembro); preço de referência 0,16 €/kWh."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BudgetThreshold, Tariff, TariffKind
from homemind.features.billing import budgets, tariff
from homemind.features.billing.tests.test_budgets import _consumo, _definir

H = f"/api/households/{fx.HOUSEHOLD}"
ANA, LANDLORD, OPERATOR = ({"x-test-sub": s} for s in ("sub-ana", "sub-senhorio", "sub-operador"))
LISBOA = ZoneInfo("Europe/Lisbon")
BI = Tariff(
    kind=TariffKind.bi_hourly,
    price_millicents_per_kwh=20_000,  # 0,20 € fora do vazio
    offpeak_price_millicents_per_kwh=10_000,  # 0,10 € no vazio
)


def _at(day, hour=0):
    return datetime(2026, 11, day, hour, tzinfo=UTC)


def _valor(wh, start, hours):
    return tariff.value_millicents(BI, LISBOA, wh, start, start + timedelta(hours=hours))


# --- tarifário ----------------------------------------------------------------------------------


def test_bi_horario_valoriza_cada_kwh_a_hora_em_que_foi_gasto():
    # terça 21h–23h: 1 kWh fora do vazio (0,20 €) + 1 kWh no vazio (0,10 €)
    assert tariff.cents(_valor(2000, _at(17, 21), 2)) == 30
    assert tariff.cents(_valor(2000, _at(21, 12), 2)) == 20  # sábado: tudo vazio
    assert tariff.cents(_valor(1000, _at(17, 7), 2)) == 15  # 07h–09h: metade em cada
    instantaneo = tariff.value_millicents(BI, LISBOA, 1000, _at(17, 7), None)
    assert tariff.cents(instantaneo) == 10  # sem duração: o preço da hora de início
    simples = Tariff(kind=TariffKind.simple, price_millicents_per_kwh=16_000)
    assert tariff.cents(tariff.value_millicents(simples, LISBOA, 2000, _at(17, 21), None)) == 32


def test_tarifa_da_casa_definida_pelo_senhorio(client):
    url = f"{H}/tariff"
    s = client.get(url, headers=ANA).json()
    assert s["source"] == "reference"
    assert s["tariff"] == {
        "kind": "simple",
        "price_millicents_per_kwh": 16_000,
        "offpeak_price_millicents_per_kwh": None,
    }
    body = BI.model_dump(mode="json")
    r = client.put(url, json=body, headers=LANDLORD)
    assert r.status_code == 200 and r.json() == {"tariff": body, "source": "configured"}
    assert client.get(url, headers=ANA).json()["tariff"]["kind"] == "bi_hourly"


def test_tarifa_permissoes_e_validacao(client):
    url = f"{H}/tariff"
    body = BI.model_dump(mode="json")
    assert client.put(url, json=body, headers=ANA).status_code == 403
    assert client.get(url, headers=OPERATOR).status_code == 403
    assert client.put(url, json=body, headers=OPERATOR).status_code == 403
    sem_vazio = {"kind": "bi_hourly", "price_millicents_per_kwh": 20_000}
    vazio_no_simples = {**body, "kind": "simple"}
    acima_de_1_euro = {"kind": "simple", "price_millicents_per_kwh": 100_001}
    for bad in (sem_vazio, vazio_no_simples, acima_de_1_euro):
        assert client.put(url, json=bad, headers=LANDLORD).status_code == 400


def test_sem_preco_nem_fatura_a_tarifa_e_desconhecida(app, client):
    app.state.db.run_sync(
        lambda c: c.execute("UPDATE household SET energy_price_millicents_per_kwh = NULL")
    )
    assert client.get(f"{H}/tariff", headers=ANA).json() == {"tariff": None, "source": None}


def test_mudar_a_tarifa_reavalia_o_orcamento(app, client):
    # segunda às 23h: 140 kWh no quarto da Ana, no vazio
    client.put(f"{H}/tariff", json=BI.model_dump(mode="json"), headers=LANDLORD)
    _consumo(app, "noite", 140_000, started=_at(2, 23))
    s = _definir(client, 25)
    assert (s["confirmed_cents"], s["pct"]) == (1400, 56)  # 0,10 €/kWh
    simples = {"kind": "simple", "price_millicents_per_kwh": 16_000}
    assert client.put(f"{H}/tariff", json=simples, headers=LANDLORD).status_code == 200
    s = client.get(f"{H}/budgets/me", headers=ANA).json()
    assert (s["confirmed_cents"], s["pct"]) == (2240, 89)
    avisos = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT seq FROM domain_event WHERE type = 'alerts.threshold_crossed'"
        ).fetchall()
    )
    assert len(avisos) == 2  # 50 % ao definir; 80 % logo ao mudar a tarifa


# --- previsão -----------------------------------------------------------------------------------


def _diarios(app, kwh_por_dia):
    for i, kwh in enumerate(kwh_por_dia):
        _consumo(app, f"dia-{i + 1}", kwh * 1000, started=_at(i + 1))


def test_mes_vazio_ou_poucos_dias_nao_tem_previsao(app, client, now):
    now["value"] = _at(16)
    assert client.get(f"{H}/budgets/me", headers=ANA).json()["forecast"] is None
    _consumo(app, "recente", 10_000, started=_at(14))  # 2 dias de dados
    s = client.get(f"{H}/budgets/me", headers=ANA).json()
    assert s["spent_cents"] == 160 and s["forecast"] is None


def test_ritmo_constante_previsao_exata(app, client, now):
    now["value"] = _at(16)  # 15 dias observados, faltam 15
    _diarios(app, [10] * 15)  # 1,60 € por dia no quarto da Ana
    s = client.get(f"{H}/budgets/me", headers=ANA).json()
    assert s["spent_cents"] == 2400
    assert s["forecast"] == {
        "cents": 4800,
        "low_cents": 4800,
        "high_cents": 4800,
        "observed_days": 15,
    }


def test_ritmo_irregular_mostra_intervalo(app, client, now):
    now["value"] = _at(16)
    _diarios(app, [5, 15] * 7 + [10])  # mesma média (10 kWh/dia), dias muito diferentes
    f = client.get(f"{H}/budgets/me", headers=ANA).json()["forecast"]
    assert f["cents"] == 4800
    assert 2400 <= f["low_cents"] < 4800 < f["high_cents"]
    simetria = (f["high_cents"] - 4800) - (4800 - f["low_cents"])
    assert abs(simetria) <= 1  # simétrico (± o arredondamento)


def test_previsao_inclui_a_base_do_mes_inteiro(app, client, now):
    outubro = {
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    bill = client.post(f"{H}/bills", json=outubro, headers=LANDLORD).json()["id"]
    assert client.post(f"{H}/bills/{bill}/finalize", headers=LANDLORD).status_code == 200
    now["value"] = _at(16)
    _diarios(app, [10] * 15)
    f = client.get(f"{H}/budgets/me", headers=ANA).json()["forecast"]
    assert f["cents"] == 4800 + round(3000 * 30 / 31)  # 30 € de base em outubro (31 dias)


def test_aviso_de_orcamento_leva_a_previsao(app, client, now):
    now["value"] = _at(16)
    _diarios(app, [10] * 15)
    _definir(client, 30)  # 24 € = 80 %
    [row] = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT payload_json FROM domain_event WHERE type = 'alerts.threshold_crossed'"
        ).fetchall()
    )
    data = BudgetThreshold.model_validate_json(row["payload_json"])
    assert (data.pct, data.spent_cents, data.forecast_cents) == (80, 2400, 4800)


def test_previsao_pura_e_reproduzivel(app, now):
    now["value"] = _at(16)
    _diarios(app, [5, 15] * 7 + [10])

    def ler(conn):
        return budgets.month_spend(conn, fx.HOUSEHOLD, fx.ANA, "2026-11", _at(16)).forecast

    assert app.state.db.run_sync(ler) == app.state.db.run_sync(ler)
