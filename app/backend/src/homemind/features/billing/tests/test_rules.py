"""Regras da casa versionadas (HOUSE-04): relógio fixo, casa demo, consumos SIMULADOS."""

import time
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

H = {
    s: {"x-test-sub": f"sub-{s}"}
    for s in ("ana", "bruno", "carla", "diogo", "senhorio", "operador")
}
RULES = f"/api/households/{fx.HOUSEHOLD}/rules"
NOTIFS = f"/api/households/{fx.HOUSEHOLD}/notifications"
EQUAL = {"common_area_rule": "equal", "ask_threshold_cents": 50, "ask_timeout_hours": 24}
DEZ = datetime(2026, 12, 1, tzinfo=UTC)  # Lisboa em dezembro = UTC


def _propor(client, body=EQUAL, who="ana"):
    r = client.put(f"{RULES}/next", json=body, headers=H[who])
    assert r.status_code == 200, r.text
    return r.json()


def _votar(client, who, approve=True):
    return client.post(f"{RULES}/next/vote", json={"approve": approve}, headers=H[who])


def _agendar(client, body=EQUAL, who="ana"):
    """Proposta + um segundo «sim»: 2 de 4 moradores é a maioria (pelo menos metade)."""
    _propor(client, body, who)
    r = _votar(client, "bruno" if who != "bruno" else "carla")
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


def test_proposta_so_fica_agendada_com_a_maioria(client):
    r = _propor(client)
    assert r["upcoming"] is None  # 1 de 4 ainda não é maioria
    p = r["proposal"]
    assert (p["status"], p["approvals"], p["rejections"], p["eligible"], p["needed"]) == (
        "open", 1, 0, 4, 2
    )  # fmt: skip
    assert p["my_vote"] is True and p["proposed_by_me"] is True
    other = client.get(RULES, headers=H["bruno"]).json()["proposal"]
    assert other["my_vote"] is None and other["proposed_by_me"] is False
    r = _votar(client, "bruno").json()
    assert r["proposal"] is None and r["upcoming"]["policy"]["common_area_rule"] == "equal"
    assert r["upcoming"]["created_by_resident_id"] == str(fx.ANA)  # o autor da proposta


def test_rejeitada_quando_a_maioria_ja_e_impossivel(client):
    _propor(client)
    assert _votar(client, "bruno", False).json()["proposal"]["rejections"] == 1
    r = _votar(client, "carla", False).json()  # 2 «não»: ana + diogo ainda fazem 2 «sim»
    assert r["proposal"]["status"] == "open"
    r = _votar(client, "diogo", False).json()
    assert r["proposal"] is None and r["upcoming"] is None
    assert _votar(client, "ana").status_code == 400  # já não há nada aberto


def test_voto_pode_mudar_e_so_o_autor_retira(client):
    _propor(client)
    _votar(client, "bruno", False)
    assert client.delete(f"{RULES}/next", headers=H["bruno"]).status_code == 403
    r = _votar(client, "bruno", True).json()  # mudou de ideias: maioria
    assert r["upcoming"] is not None
    assert client.delete(f"{RULES}/next", headers=H["ana"]).status_code == 400  # nada aberto
    _propor(client, {**EQUAL, "common_area_rule": "ask"}, "carla")  # desfazer também vota
    r = client.delete(f"{RULES}/next", headers=H["carla"])
    assert r.status_code == 200 and r.json()["proposal"] is None and r.json()["upcoming"]


def test_nova_proposta_substitui_a_aberta_e_nao_herda_votos(client):
    _propor(client)
    r = _propor(client, {**EQUAL, "common_area_rule": "ask", "ask_threshold_cents": 100}, "bruno")
    assert r["proposal"]["approvals"] == 1 and r["proposal"]["policy"]["ask_threshold_cents"] == 100
    r = _votar(client, "ana").json()
    assert r["upcoming"]["policy"]["ask_threshold_cents"] == 100
    assert len(r["history"]) == 1  # nenhuma valeu ainda


def test_nao_se_propoe_a_regra_que_ja_vai_valer(client):
    same = {"common_area_rule": "ask", "ask_threshold_cents": 50, "ask_timeout_hours": 24}
    r = client.put(f"{RULES}/next", json=same, headers=H["ana"])
    assert r.status_code == 400


def test_proposta_caduca_quando_o_mes_comeca(client, now):
    _propor(client)
    now["value"] = DEZ + timedelta(hours=1)
    r = client.get(RULES, headers=H["ana"]).json()
    assert r["proposal"] is None and r["current"]["policy"]["common_area_rule"] == "ask"
    assert _votar(client, "bruno").status_code == 400  # caducou; dezembro não muda


def test_versao_que_ja_comecou_nao_se_apaga(client, now):
    _agendar(client)
    now["value"] = DEZ + timedelta(days=4)
    r = client.get(RULES, headers=H["ana"]).json()
    assert r["current"]["policy"]["common_area_rule"] == "equal" and r["upcoming"] is None
    assert [v["effective_from"] for v in r["history"]] == ["2026-12-01", None]
    assert client.delete(f"{RULES}/next", headers=H["ana"]).status_code == 400
    r = _agendar(client, {**EQUAL, "common_area_rule": "ask"})
    assert r["upcoming"]["effective_from"] == "2027-01-01"


def test_regra_c_propoe_se_como_as_outras(client):
    r = client.put(
        f"{RULES}/next", json={**EQUAL, "common_area_rule": "presence"}, headers=H["ana"]
    )
    assert r.status_code == 200
    proposta = client.get(RULES, headers=H["ana"]).json()["proposal"]
    assert proposta["policy"]["common_area_rule"] == "presence"


def test_permissoes(client):
    assert client.get(RULES, headers=H["senhorio"]).status_code == 200  # lê
    assert client.put(f"{RULES}/next", json=EQUAL, headers=H["senhorio"]).status_code == 403
    assert _votar(client, "senhorio").status_code == 403
    assert client.delete(f"{RULES}/next", headers=H["senhorio"]).status_code == 403
    assert client.get(RULES, headers=H["operador"]).status_code == 403
    assert client.get(RULES).status_code == 401


def _avisos(client, who, title):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        found = [
            n for n in client.get(NOTIFS, headers=H[who]).json() if n["title"].startswith(title)
        ]
        if found:
            return found
        time.sleep(0.05)
    return []


def test_notificacoes_votar_e_aprovada(client):
    _propor(client)
    [n] = _avisos(client, "bruno", "Proposta de mudança da regra da sala")
    assert n["body"] == (
        "Foi proposto que, a partir de 1 de dezembro, a conta da sala é dividida por igual. "
        "Só muda se pelo menos 2 de 4 moradores aprovarem. Vota na página da casa."
    )
    assert n["ref"]["type"] == "rules_proposal"
    # o consumidor já correu (o Bruno recebeu): quem propôs e o senhorio não recebem
    for who in ("ana", "senhorio"):
        titles = [n["title"] for n in client.get(NOTIFS, headers=H[who]).json()]
        assert "Proposta de mudança da regra da sala" not in titles
    _votar(client, "bruno")
    for who in ("ana", "carla", "senhorio"):
        [n] = _avisos(client, who, "A regra da sala muda a 1 de dezembro")
    # o pedido de voto que ficou por responder já não está aberto
    end = time.monotonic() + 5
    while time.monotonic() < end:
        [vote] = _avisos(client, "carla", "Proposta de mudança da regra da sala")
        if vote["status"] == "expired":
            break
        time.sleep(0.05)
    assert vote["status"] == "expired"


def test_notificacao_quando_nao_ha_maioria(client):
    _propor(client)
    for who in ("bruno", "carla", "diogo"):
        _votar(client, who, False)
    [n] = _avisos(client, "ana", "A tua proposta de regra não foi aprovada")
    assert "já não pode aprovar" in n["body"]


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
