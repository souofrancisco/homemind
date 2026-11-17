"""Rotas de notificações: papel × rota, isolamento por casa, resposta com um só vencedor e o
fluxo ponta a ponta pelo barramento (app real, base em memória, relógio controlado)."""

import logging
import time
from datetime import timedelta
from uuid import UUID

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, stable_id
from homemind.contracts.notification import (
    Notification,
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
)
from homemind.core.events import load_events
from homemind.features.notifications.compose import compose_budget_alert, compose_confirmation
from homemind.features.notifications.sqlite import SqliteNotificationRepository
from homemind.features.notifications.tests.conftest import (
    EVA,
    HOUSE_B,
    NOW,
    as_,
)

A, B = str(fx.HOUSEHOLD), str(HOUSE_B)
ANA, BRUNO, CARLA = "sub-ana", "sub-bruno", "sub-carla"
LANDLORD, OPERATOR = "sub-senhorio", "sub-operador"
SUB_EVA, SUB_FRED = "sub-eva", "sub-fred"


def err(r):
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return r.status_code, body["error"]["code"]


def _insert(app, n: Notification) -> UUID:
    assert app.state.db.run_sync(lambda c: SqliteNotificationRepository(c).insert(n))
    return n.id


def confirmation(app, *, source="e1", consumption="consumo-1", house=fx.HOUSEHOLD, responders=None):
    """Pedido «De quem é esta conta?» já criado (sem passar pelo barramento)."""
    req = fx.confirmation_request()
    req = type(req).model_validate(
        req.model_dump()
        | {
            "consumption_event_id": stable_id("consumo", consumption),
            "expires_at": NOW + timedelta(hours=24),
        }
    )
    return _insert(
        app,
        compose_confirmation(
            req,
            household_id=house,
            responder_ids=responders or [fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO],
            origin=Origin.simulated,
            correlation_id=stable_id("corr", source),
            source_event_id=stable_id("evento", source),
            now=NOW,
        ),
    )


def budget_alert(app, resident=fx.ANA, source="limiar-80"):
    return _insert(
        app,
        compose_budget_alert(
            household_id=fx.HOUSEHOLD,
            resident_id=resident,
            budget_id=stable_id("orcamento", "x"),
            pct=80,
            spent_cents=2000,
            limit_cents=2500,
            forecast_cents=None,
            origin=Origin.simulated,
            correlation_id=stable_id("corr", source),
            source_event_id=stable_id("evento", source),
            now=NOW,
        ),
    )


def security_alert(app):
    return _insert(
        app,
        Notification(
            id=stable_id("notificacao", "seguranca"),
            household_id=fx.HOUSEHOLD,
            scope=NotificationScope.household,
            kind=NotificationKind.security_alert,
            severity=NotificationSeverity.critical,
            title="Entrada com a casa vazia",
            body="Houve uma entrada com a casa vazia (SIMULADO).",
            origin=Origin.simulated,
            correlation_id=stable_id("corr", "seguranca"),
            created_at=NOW,
        ),
    )


def url(house, nid=None, tail=""):
    base = f"/api/households/{house}/notifications"
    return f"{base}/{nid}{tail}" if nid else base


# --- papel × rota --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sub", "status", "code"),
    [
        (ANA, 200, None),
        (BRUNO, 200, None),
        (LANDLORD, 200, None),  # o senhorio tem o seu centro (sem confirmações)
        (OPERATOR, 403, "forbidden_role"),
        (SUB_EVA, 404, "household_not_found"),  # inquilina da casa B, não da A
        (SUB_FRED, 404, "household_not_found"),
        ("sub-desconhecido", 404, "household_not_found"),
    ],
)
def test_lista_e_preferencias_por_papel(client, sub, status, code):
    confirmation(client.app)
    for r in (
        client.get(url(A), headers=as_(sub)),
        client.get(f"/api/households/{A}/notification-preferences", headers=as_(sub)),
        client.put(f"/api/households/{A}/notification-preferences", json={}, headers=as_(sub)),
    ):
        assert r.status_code == status, (sub, r.text)
        if code:
            assert err(r)[1] == code


def test_fred_com_membership_terminada_nao_acede_a_casa_b(client):
    nid = confirmation(client.app, house=HOUSE_B, responders=[EVA])
    assert err(client.get(url(B), headers=as_(SUB_FRED))) == (404, "household_not_found")
    r = client.post(url(B, nid, "/respond"), json={"action_id": "mine"}, headers=as_(SUB_FRED))
    assert err(r) == (404, "household_not_found")


def test_sem_autenticacao_401(client):
    assert client.get(url(A)).status_code == 401
    nid = confirmation(client.app)
    assert client.post(url(A, nid, "/respond"), json={"action_id": "mine"}).status_code == 401


def test_operador_nao_le_nem_responde(client):
    nid = confirmation(client.app)
    for path in ("/read", "/respond"):
        r = client.post(url(A, nid, path), json={"action_id": "mine"}, headers=as_(OPERATOR))
        assert err(r) == (403, "forbidden_role")


# --- visibilidade: o senhorio nunca vê nem responde a confirmações ---------------------------


def test_senhorio_nunca_ve_confirmacoes_nem_alertas_de_seguranca(client):
    nid = confirmation(client.app)
    sec = security_alert(client.app)
    landlord = client.get(url(A), headers=as_(LANDLORD)).json()
    assert landlord == []  # nem confirmações nem alertas de segurança (presença)
    assert str(nid) not in str(landlord) and str(sec) not in str(landlord)
    ana = client.get(url(A), headers=as_(ANA)).json()
    assert {n["kind"] for n in ana} == {"confirmation_request", "security_alert"}
    # nem ler nem responder: 404 como se não existisse
    for path, body in (("/read", None), ("/respond", {"action_id": "mine"})):
        r = client.post(url(A, nid, path), json=body, headers=as_(LANDLORD))
        assert err(r) == (404, "notification_not_found")
    # o alerta de segurança (derivado de presença) também é invisível ao senhorio: 404
    r = client.post(url(A, sec, "/respond"), json={"action_id": "mine"}, headers=as_(LANDLORD))
    assert err(r) == (404, "notification_not_found")


def test_notificacao_pessoal_so_chega_ao_destinatario(client):
    nid = budget_alert(client.app, fx.ANA)
    assert [n["id"] for n in client.get(url(A), headers=as_(ANA)).json()] == [str(nid)]
    for sub in (BRUNO, LANDLORD):
        assert client.get(url(A), headers=as_(sub)).json() == []
        r = client.post(url(A, nid, "/read"), headers=as_(sub))
        assert err(r) == (404, "notification_not_found")


def test_notificacao_da_casa_a_pelo_caminho_da_casa_b_e_404(client):
    nid = confirmation(client.app)
    # Bruno é inquilino das duas casas; o caminho da casa B não dá acesso à notificação da A
    for path, body in (("/read", None), ("/respond", {"action_id": "mine"})):
        r = client.post(url(B, nid, path), json=body, headers=as_(BRUNO))
        assert err(r) == (404, "notification_not_found")
    assert client.get(url(B), headers=as_(BRUNO)).json() == []
    assert len(client.get(url(A), headers=as_(BRUNO)).json()) == 1


def test_a_vista_nunca_traz_ids_de_pessoas(client):
    confirmation(client.app)
    text = client.get(url(A), headers=as_(ANA)).text
    for person in (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO, fx.LANDLORD):
        assert str(person) not in text
    assert "responder_ids" not in text and "correlation_id" not in text


# --- lista: filtros e limites --------------------------------------------------------------------


def test_lista_filtros_e_limite(client):
    confirmation(client.app)
    budget_alert(client.app)
    all_ = client.get(url(A), headers=as_(ANA)).json()
    assert len(all_) == 2
    personal = client.get(url(A) + "?scope=personal", headers=as_(ANA)).json()
    assert [n["kind"] for n in personal] == ["budget_alert"]
    assert len(client.get(url(A) + "?limit=1", headers=as_(ANA)).json()) == 1
    assert client.get(url(A) + "?status=read", headers=as_(ANA)).json() == []
    assert len(client.get(url(A) + "?status=unread", headers=as_(ANA)).json()) == 2


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=x", "status=lida", "scope=tudo"])
def test_query_invalida_400(client, query):
    r = client.get(url(A) + "?" + query, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")


def test_id_de_notificacao_invalido_400(client):
    r = client.post(f"/api/households/{A}/notifications/nao-e-uuid/read", headers=as_(ANA))
    assert err(r) == (400, "invalid_request")


# --- ler ------------------------------------------------------------------------------------------


def test_ler_e_por_residente_nas_da_casa(client):
    nid = confirmation(client.app)
    r = client.post(url(A, nid, "/read"), headers=as_(ANA))
    assert r.status_code == 200 and r.json()["status"] == "read"
    assert client.get(url(A), headers=as_(ANA)).json()[0]["status"] == "read"
    assert client.get(url(A), headers=as_(BRUNO)).json()[0]["status"] == "unread"
    # repetir é idempotente
    assert client.post(url(A, nid, "/read"), headers=as_(ANA)).json()["status"] == "read"


def test_ler_pessoal_muda_o_estado(client):
    nid = budget_alert(client.app)
    assert client.post(url(A, nid, "/read"), headers=as_(ANA)).json()["status"] == "read"
    assert client.get(url(A) + "?status=read", headers=as_(ANA)).json()[0]["id"] == str(nid)


# --- responder -----------------------------------------------------------------------------------


def test_resposta_feliz_um_vencedor_e_um_evento(client, caplog):
    nid = confirmation(client.app)
    with caplog.at_level(logging.WARNING):
        win = client.post(url(A, nid, "/respond"), json={"action_id": "mine"}, headers=as_(ANA))
    assert win.status_code == 200, win.text
    body = win.json()
    assert body["status"] == "actioned" and body["can_respond"] is False
    assert body["response"]["action_id"] == "mine" and body["response"]["by_me"] is True
    assert str(fx.ANA) not in win.text
    assert not [r for r in caplog.records if "publicar" in r.getMessage()]
    # outro inquilino perde: 409 e a resposta de Ana fica
    lose = client.post(url(A, nid, "/respond"), json={"action_id": "everyone"}, headers=as_(BRUNO))
    assert err(lose) == (409, "already_responded")
    seen = client.get(url(A), headers=as_(BRUNO)).json()[0]
    assert seen["response"] == {
        "action_id": "mine",
        "responded_at": seen["response"]["responded_at"],
        "by_me": False,
    }
    events = client.app.state.db.run_sync(
        lambda c: load_events(c, types=["notification.responded"])
    )
    assert len(events) == 1
    ev = events[0].event
    assert isinstance(ev, de.NotificationResponded)
    assert ev.data.response.resident_id == fx.ANA and ev.data.response.action_id == "mine"
    assert ev.data.ref is not None and ev.provenance.origin is Origin.simulated


def test_o_mesmo_inquilino_a_repetir_e_409(client):
    nid = confirmation(client.app)
    for expected in (200, 409, 409):
        r = client.post(url(A, nid, "/respond"), json={"action_id": "mine"}, headers=as_(ANA))
        assert r.status_code == expected
    assert err(r) == (409, "already_responded")
    assert (
        len(
            client.app.state.db.run_sync(lambda c: load_events(c, types=["notification.responded"]))
        )
        == 1
    )


def test_depois_de_expirar_409_notification_expired(client, now):
    nid = confirmation(client.app)
    now["value"] = NOW + timedelta(hours=25)
    r = client.post(url(A, nid, "/respond"), json={"action_id": "mine"}, headers=as_(ANA))
    assert err(r) == (409, "notification_expired")
    view = client.get(url(A), headers=as_(ANA)).json()[0]
    assert view["status"] == "expired" and view["can_respond"] is False
    assert (
        client.app.state.db.run_sync(lambda c: load_events(c, types=["notification.responded"]))
        == []
    )


def test_acao_desconhecida_400_e_nao_consome(client):
    nid = confirmation(client.app)
    r = client.post(url(A, nid, "/respond"), json={"action_id": "desliga"}, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")
    ok = client.post(url(A, nid, "/respond"), json={"action_id": "everyone"}, headers=as_(ANA))
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"action_id": "Mine"},
        {"action_id": "mine", "resident_id": str(fx.BRUNO)},
        {"action_id": 1},
    ],
)
def test_corpo_invalido_400(client, body):
    nid = confirmation(client.app)
    r = client.post(url(A, nid, "/respond"), json=body, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")


def test_inexistente_404(client):
    r = client.post(
        url(A, stable_id("nada"), "/respond"), json={"action_id": "mine"}, headers=as_(ANA)
    )
    assert err(r) == (404, "notification_not_found")


def test_inquilino_fora_dos_responsaveis_403(client):
    nid = confirmation(client.app, responders=[fx.ANA])
    r = client.post(url(A, nid, "/respond"), json={"action_id": "mine"}, headers=as_(BRUNO))
    assert err(r) == (403, "forbidden_role")


# --- ponta a ponta pelo barramento ----------------------------------------------------------------


def test_pedido_do_barramento_chega_a_ana_e_nao_ao_senhorio(client):
    req = fx.confirmation_request()
    req = type(req).model_validate(
        req.model_dump() | {"eligible_resident_ids": [fx.LANDLORD, fx.ANA, fx.BRUNO]}
    )
    ev = de.BillingConfirmationNeeded(
        ts=NOW, household_id=fx.HOUSEHOLD, provenance=fx.SIM_INFERRED, data=req
    )
    client.app.state.bus.publish_threadsafe(ev)
    deadline = time.monotonic() + 3.0
    seen = []
    while time.monotonic() < deadline and not seen:
        seen = client.get(url(A), headers=as_(ANA)).json()
        time.sleep(0.05)
    assert [n["kind"] for n in seen] == ["confirmation_request"], "consumidor não entregou"
    assert seen[0]["origin"] == "simulated" and "(SIMULADO)" in seen[0]["body"]
    assert seen[0]["can_respond"] is True
    assert client.get(url(A), headers=as_(LANDLORD)).json() == []
    created = client.app.state.db.run_sync(lambda c: load_events(c, types=["notification.created"]))
    assert len(created) == 1
    # e é possível responder a esse pedido
    r = client.post(
        url(A, seen[0]["id"], "/respond"), json={"action_id": "everyone"}, headers=as_(ANA)
    )
    assert r.status_code == 200


# --- preferências ---------------------------------------------------------------------------------


def test_preferencias_por_omissao_e_ida_e_volta(client):
    pref = f"/api/households/{A}/notification-preferences"
    default = client.get(pref, headers=as_(ANA)).json()
    assert default == {"resident_id": str(fx.ANA), "quiet_hours": None, "disabled_kinds": []}
    body = {
        "quiet_hours": {"start": "22:00:00", "end": "08:00:00"},
        "disabled_kinds": ["saving_tip", "saving_tip", "peak_alert"],
    }
    put = client.put(pref, json=body, headers=as_(ANA))
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["resident_id"] == str(fx.ANA)
    assert saved["disabled_kinds"] == ["saving_tip", "peak_alert"]
    assert client.get(pref, headers=as_(ANA)).json() == saved
    # por pessoa: os outros ficam com a omissão
    assert client.get(pref, headers=as_(BRUNO)).json()["disabled_kinds"] == []
    # o senhorio também tem as suas
    assert client.put(pref, json={}, headers=as_(LANDLORD)).status_code == 200
    # PUT substitui (não faz merge)
    assert client.put(pref, json={}, headers=as_(ANA)).json()["quiet_hours"] is None


def test_preferencias_sao_por_casa(client):
    """Bruno é inquilino nas casas A e B: o PUT numa não altera a outra (silêncio local)."""
    pa = f"/api/households/{A}/notification-preferences"
    pb = f"/api/households/{B}/notification-preferences"
    body = {
        "quiet_hours": {"start": "22:00:00", "end": "08:00:00"},
        "disabled_kinds": ["peak_alert"],
    }
    assert client.put(pa, json=body, headers=as_(BRUNO)).status_code == 200
    assert client.get(pa, headers=as_(BRUNO)).json()["disabled_kinds"] == ["peak_alert"]
    default_b = client.get(pb, headers=as_(BRUNO)).json()
    assert default_b == {"resident_id": str(fx.BRUNO), "quiet_hours": None, "disabled_kinds": []}
    other = {"disabled_kinds": ["saving_tip"]}
    assert client.put(pb, json=other, headers=as_(BRUNO)).status_code == 200
    assert client.get(pa, headers=as_(BRUNO)).json()["disabled_kinds"] == ["peak_alert"]
    assert client.get(pb, headers=as_(BRUNO)).json()["disabled_kinds"] == ["saving_tip"]
    rows = client.app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT household_id FROM notification_preferences WHERE resident_id = ?",
            (str(fx.BRUNO),),
        ).fetchall()
    )
    assert {r["household_id"] for r in rows} == {A, B}


def test_preferencias_nunca_aceitam_resident_id_nem_desligar_seguranca(client):
    pref = f"/api/households/{A}/notification-preferences"
    other = {"resident_id": str(fx.BRUNO)}
    assert err(client.put(pref, json=other, headers=as_(ANA))) == (400, "invalid_request")
    r = client.put(pref, json={"disabled_kinds": ["security_alert"]}, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")
    assert "security" not in r.text and "ValidationError" not in r.text
    bad = {"quiet_hours": {"start": "25:00", "end": "08:00"}}
    assert err(client.put(pref, json=bad, headers=as_(ANA))) == (400, "invalid_request")
    assert client.get(pref, headers=as_(ANA)).json()["disabled_kinds"] == []


def test_consumidor_usa_o_relogio_sobrescrito_e_ignora_pedido_expirado(client, now):
    """D6: o relógio do consumidor é o mesmo das rotas. Com o relógio de teste depois de
    `expires_at`, o pedido é um no-op (processado, sem notificação nem `notification.created`)."""
    now["value"] = fx.T0 + timedelta(hours=48)  # `expires_at` do pedido é T0 + 24 h
    ev = de.BillingConfirmationNeeded(
        ts=NOW,
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_INFERRED,
        data=fx.confirmation_request(),
    )
    stored = client.app.state.bus.publish_threadsafe(ev)

    def processed() -> bool:
        return bool(
            client.app.state.db.run_sync(
                lambda c: c.execute(
                    "SELECT 1 FROM processed_event WHERE event_id = ?", (str(stored.event.id),)
                ).fetchone()
            )
        )

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not processed():
        time.sleep(0.05)
    assert processed(), "consumidor não processou o evento"
    assert client.get(url(A), headers=as_(ANA)).json() == []
    created = client.app.state.db.run_sync(lambda c: load_events(c, types=["notification.created"]))
    assert created == []
