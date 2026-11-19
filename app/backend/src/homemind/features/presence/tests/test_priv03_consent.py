# ruff: noqa: E501
"""PRIV-03 #51 (D-37): consentimento por fonte (Wi-Fi, aparelho a ligar, resposta manual), gates de
recolha, revogação por fonte, registo só de acrescentar, RBAC e isolamento. Relógio simulado, sem
rede nem hardware."""

import hashlib
import json
import sqlite3
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.domain_events import NotificationResponded, NotificationRespondedData
from homemind.contracts.notification import NotificationRef, NotificationResponse, RefType
from homemind.contracts.presence import PresenceState
from homemind.features.households.tests.conftest import HOUSE_B
from homemind.features.presence import consent_texts
from homemind.features.presence import retention as rt
from homemind.features.presence.tests.conftest import (
    MAC_BRUNO,
    SALT,
    TOKEN,
    A,
    as_,
    cues,
    set_presence_opt_in,
)
from homemind.features.presence.tests.test_pres04 import (
    MEASURED,
    consumption_started,
    events,
    put_me,
    settle,
    state_of,
)
from homemind.features.presence.tests.test_priv03 import changed, financial, put
from homemind.features.presence.wifi import match_key

BRUNO, ANA, CARLA, LANDLORD, OPERATOR = (
    "sub-bruno", "sub-ana", "sub-carla", "sub-senhorio", "sub-operador",
)  # fmt: skip
V = consent_texts.TEXT_VERSION
URL = f"/api/presence/consents?household_id={A}"


def src_url(source, house=A):
    return f"/api/presence/consents/{source}?household_id={house}"


def q(client, sql, *args):
    return client.app_state.db.run_sync(lambda c: [tuple(r) for r in c.execute(sql, args)])


def view(client, sub=BRUNO, house=A):
    r = client.get(f"/api/presence/consents?household_id={house}", headers=as_(sub))
    assert r.status_code == 200, r.text
    return r.json()


def enabled(client, sub=BRUNO):
    return {s["source"]: s["enabled"] for s in view(client, sub)["sources"]}


def grant(client, sub, source, version=V, house=A):
    return client.post(src_url(source, house), json={"text_version": version}, headers=as_(sub))


def revoke(client, sub, source, house=A):
    return client.delete(src_url(source, house), headers=as_(sub))


def seed_ana(client):
    """Ana com opt-in global mas SEM nenhuma fonte (o estado real por omissão)."""
    set_presence_opt_in(client.app_state.db, fx.ANA, 1)


def register_phone(client, sub, mac=MAC_BRUNO):
    r = client.post(
        f"/api/presence/devices?household_id={A}",
        json={"label": "Telemóvel", "wifi_address": mac, "consent": True},
        headers=as_(sub),
    )
    assert r.status_code == 201, r.text


def observe(client, mac):
    return client.post(
        "/api/presence/wifi/observations",
        json={"keys": [match_key(SALT, mac)]},
        headers={"x-presence-token": TOKEN},
    )


def drop_source(client, resident, source):
    """Tira uma fonte SEM passar pela API (o fixture liga as três ao Bruno)."""
    client.app_state.db.run_sync(
        lambda c: c.execute(
            "DELETE FROM presence_source_consent WHERE resident_id = ? AND source = ?",
            (str(resident), source),
        )
    )


# --- omissão, texto e versão ---------------------------------------------------------------------


def test_por_omissao_todas_as_fontes_estao_desligadas(client):
    seed_ana(client)
    v = view(client, ANA)
    assert v["presence_opt_in"] is True and v["text_version"] == V
    assert {s["source"]: s["enabled"] for s in v["sources"]} == {
        "wifi": False, "appliance": False, "manual": False,
    }  # fmt: skip
    assert all(
        s["title"] and s["collects"] and s["who_sees"] and s["how_to_revoke"] for s in v["sources"]
    )
    assert "camera" not in json.dumps(v["sources"]).lower().replace(
        "câmara", ""
    )  # a porta não tem opt-in


def test_o_texto_esta_fixado_a_versao_obriga_a_mudar_quando_o_texto_muda():
    blob = json.dumps(
        {k.value: v for k, v in consent_texts.TEXTS.items()}, sort_keys=True, ensure_ascii=False
    )
    assert (
        hashlib.sha256(blob.encode()).hexdigest()[:16] == "d993d7b3db179b3f"
    ), "O texto de consentimento mudou: mudar TEXT_VERSION e atualizar este valor"


# --- ligar --------------------------------------------------------------------------------------


def test_ligar_exige_o_opt_in_global(client):
    r = grant(client, CARLA, "wifi")  # a Carla nunca deu o opt-in global
    assert r.status_code == 409 and r.json()["error"]["code"] == "presence_opt_in_required"
    assert q(
        client, "SELECT COUNT(*) FROM presence_source_consent WHERE resident_id = ?", str(fx.CARLA)
    ) == [(0,)]


def test_ligar_com_texto_desatualizado_e_recusado_e_com_o_atual_regista_a_versao(client):
    seed_ana(client)
    r = grant(client, ANA, "manual", version="1999-01-01.0")
    assert r.status_code == 409 and r.json()["error"]["code"] == "text_version_outdated"
    assert enabled(client, ANA)["manual"] is False
    r = grant(client, ANA, "manual")
    assert r.status_code == 200 and enabled(client, ANA)["manual"] is True
    last = view(client, ANA)["history"][-1]
    assert (last["subject"], last["action"], last["text_version"], last["reason"]) == (
        "manual", "granted", V, "resident",
    )  # fmt: skip


def test_ligar_duas_vezes_nao_regista_duas_vezes(client):
    seed_ana(client)
    grant(client, ANA, "wifi")
    n = len(view(client, ANA)["history"])
    assert grant(client, ANA, "wifi").status_code == 200
    assert len(view(client, ANA)["history"]) == n


def test_fonte_desconhecida_e_corpo_com_campos_a_mais_sao_recusados(client):
    seed_ana(client)
    assert grant(client, ANA, "camera").status_code == 400
    r = client.post(src_url("wifi"), json={"text_version": V, "x": 1}, headers=as_(ANA))
    assert r.status_code == 400


# --- gates de recolha (mesma transação que grava a pista) -----------------------------------------


def test_wifi_sem_opt_in_da_fonte_nao_grava_pista_nem_estado(client):
    seed_ana(client)
    register_phone(client, ANA)  # telemóvel com consentimento próprio, fonte desligada
    assert observe(client, MAC_BRUNO).status_code == 204
    assert cues(client.app_state.db) == []
    assert grant(client, ANA, "wifi").status_code == 200
    client.clock.advance(minutes=5)
    observe(client, MAC_BRUNO)
    settle(client)
    [c] = cues(client.app_state.db, "wifi")
    assert c.data.resident_id == fx.ANA


def test_wifi_ligado_e_depois_revogado_para_logo_de_recolher(client):
    seed_ana(client)
    grant(client, ANA, "wifi")
    register_phone(client, ANA)
    observe(client, MAC_BRUNO)
    assert len(cues(client.app_state.db, "wifi")) == 1
    assert revoke(client, ANA, "wifi").status_code == 200
    client.clock.advance(minutes=5)
    observe(client, MAC_BRUNO)
    assert cues(client.app_state.db) == []


def test_aparelho_a_ligar_so_conta_com_a_fonte_ligada(client, clock):
    drop_source(client, fx.BRUNO, "appliance")
    consumption_started(client, clock, started_ago=timedelta(seconds=10))
    assert cues(client.app_state.db) == []
    client.app_state.db.run_sync(
        lambda c: c.execute(
            "INSERT OR REPLACE INTO presence_source_consent VALUES (?,?,?,1,'t',?)",
            (A, str(fx.BRUNO), "appliance", clock.now.isoformat()),
        )
    )
    consumption_started(client, clock, started_ago=timedelta(seconds=10), cid="outro")
    assert len(cues(client.app_state.db, "appliance")) == 1


def _responder(client, req, clock):
    client.app_state.bus.publish_threadsafe(
        NotificationResponded(
            ts=clock.now,
            household_id=fx.HOUSEHOLD,
            provenance=MEASURED,
            data=NotificationRespondedData(
                response=NotificationResponse(
                    notification_id=req.id,
                    action_id="in",
                    resident_id=fx.BRUNO,
                    responded_at=clock.now,
                ),
                ref=NotificationRef(type=RefType.presence_check, id=req.data.id),
            ),
        )
    )
    settle(client)


def test_resposta_manual_so_conta_com_a_fonte_ligada_e_nao_gasta_o_pedido(client, clock):
    put_me(client, BRUNO, "out")
    settle(client)
    clock.advance(minutes=20)
    consumption_started(client, clock, started_ago=timedelta(seconds=5))
    [req] = events(client, "presence.confirmation_needed")
    drop_source(client, fx.BRUNO, "manual")
    before = len(cues(client.app_state.db))
    _responder(client, req, clock)
    assert len(cues(client.app_state.db)) == before
    assert q(client, "SELECT answered_at FROM presence_confirmation") == [(None,)]  # não gasta


def test_sem_a_fonte_manual_o_sistema_nao_pergunta(client, clock):
    drop_source(client, fx.BRUNO, "manual")
    put_me(client, BRUNO, "out")  # pista injetada diretamente (fora do gate, só para o cenário)
    settle(client)
    clock.advance(minutes=20)
    consumption_started(client, clock, started_ago=timedelta(seconds=5))
    assert events(client, "presence.confirmation_needed") == []
    assert state_of(client)[0] == "uncertain"  # a contradição continua incerta, sem pergunta


# --- revogar UMA fonte ---------------------------------------------------------------------------


def _seed_mixed(client, clock):
    """Bruno (casa A) com pistas wifi/appliance/manual, estado, telemóvel, agregados e mudanças;
    a Ana (colega), a casa B e dados financeiros para provar que nada disto é tocado."""
    db = client.app_state.db
    register_phone(client, BRUNO)
    observe(client, MAC_BRUNO)  # pista wifi real, pelo gate
    put_me(client, BRUNO, "in")  # manual
    consumption_started(client, clock, started_ago=timedelta(seconds=5))  # appliance
    settle(client)
    set_presence_opt_in(db, fx.ANA, 1)
    db.run_sync(
        lambda c: c.execute(
            "INSERT OR REPLACE INTO presence_source_consent VALUES (?,?,?,1,'t',?)",
            (A, str(fx.ANA), "wifi", clock.now.isoformat()),
        )
    )
    put_me(client, ANA, "in")
    from homemind.features.presence.tests.test_priv03 import cue as mk_cue

    put(
        db,
        mk_cue(fx.ANA, clock.now, n=91),
        changed(fx.ANA, clock.now, PresenceState.home),
        financial(clock.now, "x"),
    )
    set_presence_opt_in(db, fx.BRUNO, 1)
    db.run_sync(
        lambda c: c.execute(
            "INSERT OR REPLACE INTO presence_source_consent VALUES (?,?,?,1,'t',?)",
            (str(HOUSE_B), str(fx.BRUNO), "wifi", clock.now.isoformat()),
        )
    )
    put(db, mk_cue(fx.BRUNO, clock.now, n=92, house=HOUSE_B))


def test_revogar_o_wifi_apaga_so_as_pistas_wifi_do_proprio_e_mantem_o_resto(client, clock):
    from homemind.features.presence.tests.test_priv03 import financial_snapshot

    _seed_mixed(client, clock)
    db = client.app_state.db

    def own(src):
        return len(
            [
                c
                for c in cues(db, src)
                if c.data.resident_id == fx.BRUNO and c.household_id == fx.HOUSEHOLD
            ]
        )

    assert own("wifi") == 1 and own("appliance") == 1 and own("manual") == 1
    fin = financial_snapshot(db)
    ana_cues = len([c for c in cues(db) if c.data.resident_id == fx.ANA])
    b_cues = len([c for c in cues(db) if c.household_id == HOUSE_B])

    r = revoke(client, BRUNO, "wifi")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "wifi" and body["enabled"] is False and body["erased_cues"] == 1
    assert own("wifi") == 0 and own("appliance") == 1 and own("manual") == 1  # só a fonte revogada
    assert len([c for c in cues(db) if c.data.resident_id == fx.ANA]) == ana_cues  # colega intacta
    assert len([c for c in cues(db) if c.household_id == HOUSE_B]) == b_cues  # outra casa intacta
    assert financial_snapshot(db)[0] == fin[0]  # nenhum evento financeiro mudou
    assert enabled(client) == {"wifi": False, "appliance": True, "manual": True}
    assert q(
        client,
        "SELECT wifi_opt_in, match_key FROM presence_device WHERE resident_id = ?",
        str(fx.BRUNO),
    ) == [
        (
            0,
            q(
                client,
                "SELECT 'revoked:' || id FROM presence_device WHERE resident_id = ?",
                str(fx.BRUNO),
            )[0][0],
        )
    ]
    assert enabled(client, ANA) == {"wifi": True, "appliance": False, "manual": False}
    # o estado recalcula-se com o que sobra (aparelho + manual): continua «em casa»
    assert state_of(client)[0] == "in"


def test_revogar_a_unica_fonte_apaga_o_estado_e_nao_fica_em_casa_nem_fora(client, clock):
    drop_source(client, fx.BRUNO, "appliance")
    drop_source(client, fx.BRUNO, "manual")
    register_phone(client, BRUNO)
    observe(client, MAC_BRUNO)
    settle(client)
    assert state_of(client)[0] == "in"
    revoke(client, BRUNO, "wifi")
    state, reason, own = state_of(client)
    assert (state, reason, own["sources"]) == ("uncertain", "no_recent_cues", [])
    assert q(
        client, "SELECT COUNT(*) FROM presence_state WHERE resident_id = ?", str(fx.BRUNO)
    ) == [(0,)]
    assert [
        c
        for c in events(client, "presence.changed")
        if fx.BRUNO == c.data.resident_id and "wifi" in [s.value for s in c.data.sources]
    ] == []


def test_revogar_e_idempotente_e_so_regista_uma_vez(client, clock):
    _seed_mixed(client, clock)
    revoke(client, BRUNO, "wifi")
    n_log = len(view(client)["history"])
    n_events = len(events(client, "presence.source_revoked"))
    r = revoke(client, BRUNO, "wifi")
    assert r.status_code == 200 and (r.json()["erased_cues"], r.json()["erased_other"]) == (0, 0)
    assert len(view(client)["history"]) == n_log
    assert len(events(client, "presence.source_revoked")) == n_events == 1
    revoked = [h for h in view(client)["history"] if h["action"] == "revoked"]
    assert [(h["subject"], h["reason"]) for h in revoked] == [("wifi", "resident")]


def test_revogar_o_manual_apaga_os_pedidos_e_as_respostas_e_mantem_o_wifi(client, clock):
    _seed_mixed(client, clock)
    r = revoke(client, BRUNO, "manual")
    assert r.status_code == 200
    assert [
        c.data.source.value
        for c in cues(client.app_state.db)
        if c.data.resident_id == fx.BRUNO and c.household_id == fx.HOUSEHOLD
    ].count("manual") == 0
    assert q(
        client, "SELECT COUNT(*) FROM presence_confirmation WHERE resident_id = ?", str(fx.BRUNO)
    ) == [(0,)]
    assert enabled(client)["wifi"] is True


def test_depois_de_revogar_pode_voltar_a_ligar_e_fica_no_registo(client):
    seed_ana(client)
    grant(client, ANA, "wifi")
    revoke(client, ANA, "wifi")
    assert grant(client, ANA, "wifi").status_code == 200
    h = [
        (x["subject"], x["action"]) for x in view(client, ANA)["history"] if x["subject"] == "wifi"
    ]
    assert h == [("wifi", "granted"), ("wifi", "revoked"), ("wifi", "granted")]


# --- opt-in global ------------------------------------------------------------------------------


def test_revogar_o_opt_in_global_desliga_as_fontes_logo_e_um_novo_opt_in_nao_as_reativa(client):
    db = client.app_state.db
    assert enabled(client)["wifi"] is True
    set_presence_opt_in(db, fx.BRUNO, 0)
    # logo, sem esperar pela varredura: as fontes ficam desligadas e há registo
    assert (
        q(
            client,
            "SELECT enabled FROM presence_source_consent WHERE resident_id = ? AND household_id = ?",
            str(fx.BRUNO),
            A,
        )
        == [(0,)] * 3
    )
    set_presence_opt_in(db, fx.BRUNO, 1)  # liga de novo, a seguir
    assert enabled(client) == {"wifi": False, "appliance": False, "manual": False}
    subjects = [(h["subject"], h["action"], h["reason"]) for h in view(client)["history"]]
    assert ("presence_opt_in", "revoked", "opt_in_revoked") in subjects
    assert ("presence_opt_in", "granted", "resident") in subjects
    assert sum(1 for s in subjects if s[0] == "wifi" and s[1] == "revoked") == 1


def test_sair_da_casa_desliga_as_fontes_e_regista_o_motivo(client):
    db = client.app_state.db
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-01' WHERE resident_id = ? AND household_id = ?",
            (str(fx.BRUNO), A),
        )
    )
    rt.erase_unconsented(db.run_sync, client.clock.now)
    assert (
        q(
            client,
            "SELECT enabled FROM presence_source_consent WHERE resident_id = ? AND household_id = ?",
            str(fx.BRUNO),
            A,
        )
        == [(0,)] * 3
    )
    assert q(
        client,
        "SELECT reason FROM presence_consent_log WHERE household_id = ? AND resident_id = ? AND action = 'revoked' AND subject = 'wifi'",
        A,
        str(fx.BRUNO),
    ) == [("left_household",)]


# --- registo só de acrescentar --------------------------------------------------------------------


def test_o_registo_nao_se_altera_nem_se_apaga(client):
    seed_ana(client)
    grant(client, ANA, "wifi")
    db = client.app_state.db
    with pytest.raises(sqlite3.DatabaseError, match="acrescentar"):
        db.run_sync(lambda c: c.execute("UPDATE presence_consent_log SET action = 'granted'"))
    with pytest.raises(sqlite3.DatabaseError, match="acrescentar"):
        db.run_sync(lambda c: c.execute("DELETE FROM presence_consent_log"))
    # a eliminação do morador também não apaga o registo de consentimentos
    set_presence_opt_in(db, fx.ANA, 0)
    rt.erase_unconsented(db.run_sync, client.clock.now)
    assert (
        q(client, "SELECT COUNT(*) FROM presence_consent_log WHERE resident_id = ?", str(fx.ANA))[
            0
        ][0]
        >= 3
    )


# --- faturação ----------------------------------------------------------------------------------


def test_a_copia_de_presenca_da_faturacao_fica_coerente(client, clock):
    _seed_mixed(client, clock)
    db = client.app_state.db
    for rid, since in (
        (fx.BRUNO, "2026-11-01T10:00:00+00:00"),
        (fx.ANA, "2026-11-01T10:00:00+00:00"),
    ):
        db.run_sync(
            lambda c, rid=rid, since=since: c.execute(
                "INSERT OR REPLACE INTO billing_presence_state VALUES (?,?,?,?,?,?)",
                (A, str(rid), since, "in", 0.95, 1),
            )
        )
    revoke(client, BRUNO, "wifi")
    settle(client)
    rows = q(client, "SELECT resident_id, since FROM billing_presence_state")
    assert (str(fx.BRUNO), "2026-11-01T10:00:00+00:00") not in rows  # o histórico do Bruno saiu
    assert (str(fx.ANA), "2026-11-01T10:00:00+00:00") in rows  # o da colega fica


# --- RBAC e isolamento --------------------------------------------------------------------------


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_senhorio_e_operador_403_em_todas_as_rotas(client, sub):
    for method, url in (
        ("get", URL), ("post", src_url("wifi")), ("delete", src_url("wifi")),
    ):  # fmt: skip
        kw = {"json": {"text_version": V}} if method == "post" else {}
        r = getattr(client, method)(url, headers=as_(sub), **kw)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role", (method, sub)


def test_nao_membro_404_e_anonimo_401(client):
    for method, url in (("get", URL), ("post", src_url("wifi")), ("delete", src_url("wifi"))):
        kw = {"json": {"text_version": V}} if method == "post" else {}
        assert getattr(client, method)(url, headers=as_("sub-eva"), **kw).status_code == 404
        assert getattr(client, method)(url, **kw).status_code == 401
    assert client.get("/api/presence/consents", headers=as_(BRUNO)).status_code == 400


def test_cross_account_a_casa_a_nao_chega_a_quem_so_e_da_casa_b(client):
    seed_ana(client)
    assert client.get(URL, headers=as_("sub-hugo")).status_code in (403, 404)  # Hugo: senhorio da B
    r = client.delete(src_url("wifi"), headers=as_("sub-fred"))
    assert r.status_code == 404


def test_cada_um_so_ve_e_altera_o_seu(client):
    seed_ana(client)
    grant(client, ANA, "wifi")
    assert enabled(client, BRUNO)["wifi"] is True
    revoke(client, ANA, "wifi")
    assert enabled(client, BRUNO)["wifi"] is True  # a revogação da Ana não toca no Bruno
    assert str(fx.ANA) not in json.dumps(view(client, BRUNO))
    assert str(fx.BRUNO) not in json.dumps(view(client, ANA))


def test_revogar_na_casa_a_nao_toca_nos_consentimentos_da_casa_b(client, clock):
    _seed_mixed(client, clock)
    revoke(client, BRUNO, "wifi", house=A)
    assert q(
        client,
        "SELECT enabled FROM presence_source_consent WHERE household_id = ? AND resident_id = ? AND source = 'wifi'",
        str(HOUSE_B),
        str(fx.BRUNO),
    ) == [(1,)]


# --- exportação ---------------------------------------------------------------------------------


def test_a_exportacao_inclui_o_registo_de_consentimentos_so_do_proprio(client):
    seed_ana(client)
    grant(client, ANA, "wifi")
    revoke(client, ANA, "wifi")
    own = client.get(f"/api/presence/export?household_id={A}", headers=as_(ANA)).json()
    assert [(h["subject"], h["action"]) for h in own["consent_history"] if h["subject"] == "wifi"] == [
        ("wifi", "granted"), ("wifi", "revoked"),
    ]  # fmt: skip
    assert {s["source"]: s["enabled"] for s in own["source_consents"]}["wifi"] is False
    other = client.get(f"/api/presence/export?household_id={A}", headers=as_(BRUNO)).json()
    assert all(h["subject"] != "wifi" or h["action"] != "revoked" for h in other["consent_history"])
    assert str(fx.ANA) not in json.dumps(other)
