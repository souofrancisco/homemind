"""Regras da casa versionadas (HOUSE-04): relógio fixo, casa demo, consumos SIMULADOS."""

from datetime import UTC, date, datetime, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, PolicyVersion
from homemind.contracts.household import CommonAreaRule, HouseholdPolicy
from homemind.features.billing import attributor
from homemind.features.billing.rules import first_of_next_month, version_on
from homemind.features.billing.tests.test_attributor import (
    _ativa,
    _consumo,
    _evento,
    _handle,
    _pedido,
)

H = {s: {"x-test-sub": f"sub-{s}"} for s in ("ana", "bruno", "senhorio", "operador")}
RULES = f"/api/households/{fx.HOUSEHOLD}/rules"
EQUAL = {"common_area_rule": "equal", "ask_threshold_cents": 50, "ask_timeout_hours": 24}
DEZ = datetime(2026, 12, 1, tzinfo=UTC)  # Lisboa em dezembro = UTC


def _agendar(client, body=EQUAL, who="ana"):
    r = client.put(f"{RULES}/next", json=body, headers=H[who])
    assert r.status_code == 200, r.text
    return r.json()


def _sala(app, at, wh=5000):
    """Aquecedor na sala (0,80 €), a começar em `at`."""
    c = _consumo(wh=wh, started_at=at, ended_at=at + timedelta(minutes=30))
    return _handle(app, _evento(c, ts=at + timedelta(minutes=30)))


# --- puras ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 11, 17), date(2026, 12, 1)), (date(2026, 12, 31), date(2027, 1, 1))],
)
def test_proximo_mes(day, expected):
    assert first_of_next_month(day) == expected


def test_versao_do_dia():
    inicial = PolicyVersion(effective_from=None, policy=HouseholdPolicy())
    dez = PolicyVersion(
        effective_from=date(2026, 12, 1),
        policy=HouseholdPolicy(common_area_rule=CommonAreaRule.equal),
    )
    assert version_on([inicial, dez], date(2026, 11, 30)) is inicial
    assert version_on([inicial, dez], date(2026, 12, 1)) is dez


# --- API -----------------------------------------------------------------------------------------


def test_sem_mudancas_vale_a_politica_inicial(client):
    r = client.get(RULES, headers=H["ana"]).json()
    assert r["current"]["effective_from"] is None
    assert r["current"]["policy"]["common_area_rule"] == "ask" and r["upcoming"] is None
    assert r["next_change_from"] == "2026-12-01"


def test_mudanca_so_vale_no_mes_seguinte(client):
    r = _agendar(client)
    assert r["current"]["policy"]["common_area_rule"] == "ask"  # novembro não muda
    assert r["upcoming"]["effective_from"] == "2026-12-01"
    assert r["upcoming"]["policy"]["common_area_rule"] == "equal"
    assert r["upcoming"]["created_by_resident_id"] == str(fx.ANA)


def test_agendar_de_novo_substitui_e_cancelar_apaga(client):
    _agendar(client)
    r = _agendar(client, {**EQUAL, "common_area_rule": "ask", "ask_threshold_cents": 100}, "bruno")
    assert r["upcoming"]["policy"]["ask_threshold_cents"] == 100
    assert len(r["history"]) == 1  # a substituída nunca valeu
    r = client.delete(f"{RULES}/next", headers=H["ana"])
    assert r.status_code == 200 and r.json()["upcoming"] is None
    assert client.delete(f"{RULES}/next", headers=H["ana"]).status_code == 400


def test_versao_que_ja_comecou_nao_se_apaga(client, now):
    _agendar(client)
    now["value"] = DEZ + timedelta(days=4)
    r = client.get(RULES, headers=H["ana"]).json()
    assert r["current"]["policy"]["common_area_rule"] == "equal" and r["upcoming"] is None
    assert [v["effective_from"] for v in r["history"]] == ["2026-12-01", None]
    assert client.delete(f"{RULES}/next", headers=H["ana"]).status_code == 400
    assert _agendar(client)["upcoming"]["effective_from"] == "2027-01-01"


def test_regra_c_ainda_nao_existe(client):
    r = client.put(
        f"{RULES}/next", json={**EQUAL, "common_area_rule": "presence"}, headers=H["ana"]
    )
    assert r.status_code == 400 and client.get(RULES, headers=H["ana"]).json()["upcoming"] is None


def test_permissoes(client):
    assert client.get(RULES, headers=H["senhorio"]).status_code == 200  # lê
    assert client.put(f"{RULES}/next", json=EQUAL, headers=H["senhorio"]).status_code == 403
    assert client.delete(f"{RULES}/next", headers=H["senhorio"]).status_code == 403
    assert client.get(RULES, headers=H["operador"]).status_code == 403
    assert client.get(RULES).status_code == 401


# --- o atribuidor decide com a regra do dia do consumo -------------------------------------------


def test_consumo_decide_com_a_regra_do_seu_dia(app, client):
    _agendar(client)  # a partir de 1/12: por igual
    novembro = fx.T0.replace(day=30, hour=23, minute=59)
    _sala(app, novembro)
    assert _pedido(app) == "pending"  # 30/11 ainda é «perguntar»
    app.state.db.run_sync(lambda c: c.execute("DELETE FROM billing_confirmation"))
    _sala(app, DEZ)
    a = _ativa(app)
    assert _pedido(app) is None and a.method is AttributionMethod.equal_fallback


def test_limiar_e_prazo_vem_da_versao(app, client):
    _agendar(client, {**EQUAL, "common_area_rule": "ask", "ask_timeout_hours": 48})
    [ev] = _sala(app, DEZ)
    assert ev.data.expires_at == DEZ + timedelta(minutes=30, hours=48)
    # sem resposta no prazo: conta comum, nunca uma cobrança individual
    [fim] = app.state.db.run_sync(lambda c: attributor.expire_pending(c, ev.data.expires_at))
    assert fim.data.target_resident_id is None
    assert fim.data.method is AttributionMethod.equal_fallback


def test_limiar_mais_alto_nao_pergunta(app, client):
    _agendar(client, {**EQUAL, "common_area_rule": "ask", "ask_threshold_cents": 100})
    _sala(app, DEZ)  # 0,80 € < 1,00 €
    assert _pedido(app) is None and _ativa(app).method is AttributionMethod.equal_fallback


def test_explicacao_mostra_a_regra_do_periodo(app, client, now):
    from homemind.features.billing.tests.test_closing import SIM, URL, _fechar

    _agendar(client)
    now["value"] = DEZ + timedelta(days=4)  # hoje vale «por igual»
    bill = client.post(URL, json=SIM, headers=H["senhorio"]).json()["id"]  # novembro
    assert _fechar(client, bill).status_code == 200
    e = client.get(f"{URL}/{bill}/receipt/explanation", headers=H["ana"]).json()
    assert e["common_area_rule"] == "ask"
