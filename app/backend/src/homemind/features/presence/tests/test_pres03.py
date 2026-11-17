"""PRES-03: declaração manual, telemóveis com opt-in, pistas Wi-Fi e respostas da app."""

import asyncio
import logging
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.domain_events import NotificationResponded, NotificationRespondedData
from homemind.contracts.notification import NotificationRef, NotificationResponse, RefType
from homemind.contracts.presence import PresenceConfirmationRequest, UncertainReason
from homemind.core.events import append_event
from homemind.features.households.tests.conftest import NOW
from homemind.features.presence import repo
from homemind.features.presence.service import WifiPoller, on_notification_responded
from homemind.features.presence.tests.conftest import (
    MAC_BRUNO,
    MAC_CARLA,
    MAC_VISITA,
    SALT,
    TOKEN,
    A,
    B,
    as_,
    cues,
    dump_text,
    set_presence_opt_in,
)
from homemind.features.presence.wifi import FakeWifiScanner, match_key

BRUNO, CARLA, LANDLORD, OPERATOR, OUTSIDER = (
    "sub-bruno", "sub-carla", "sub-senhorio", "sub-operador", "sub-eva",
)  # fmt: skip
TOK = {"x-presence-token": TOKEN}


def code(r):
    return r.status_code, r.json()["error"]["code"]


def register(client, sub, mac, household=A, label="Telemóvel"):
    return client.post(
        f"/api/presence/devices?household_id={household}",
        json={"label": label, "wifi_address": mac, "consent": True},
        headers=as_(sub),
    )


def observe(client, *macs):
    keys = [match_key(SALT, m) for m in macs]
    return client.post("/api/presence/wifi/observations", json={"keys": keys}, headers=TOK)


# --- acesso por papel ----------------------------------------------------------------------------


def _all_routes(h):
    return [
        ("PUT", f"/api/presence/me?household_id={h}", {"state": "in"}),
        ("GET", f"/api/presence/devices?household_id={h}", None),
        (
            "POST",
            f"/api/presence/devices?household_id={h}",
            {"label": "x", "wifi_address": MAC_BRUNO, "consent": True},
        ),
        ("DELETE", f"/api/presence/devices/{fx.CARLA}?household_id={h}", None),
    ]


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_landlord_and_operator_get_403_on_every_presence_route(client, sub):
    for method, url, body in _all_routes(A):
        r = client.request(method, url, json=body, headers=as_(sub))
        assert code(r) == (403, "forbidden_role"), (method, url)
    assert cues(client.app_state.db) == []


def test_outsider_gets_404_and_anonymous_401(client):
    for method, url, body in _all_routes(A):
        assert code(client.request(method, url, json=body, headers=as_(OUTSIDER)))[0] == 404
        assert client.request(method, url, json=body).status_code == 401


# --- declaração manual ---------------------------------------------------------------------------


def test_manual_declaration_records_a_cue_for_the_session_resident(client):
    r = client.put(f"/api/presence/me?household_id={A}", json={"state": "in"}, headers=as_(BRUNO))
    assert r.status_code == 200
    body = r.json()
    assert body["resident_id"] == str(fx.BRUNO)
    assert body["state"] == "in" and body["sources"] == ["manual"]
    [ev] = cues(client.app_state.db)
    assert ev.data.resident_id == fx.BRUNO and ev.data.source.value == "manual"
    assert ev.provenance == Provenance(origin=Origin.real, kind=ValueKind.measured)  # P-19
    client.put(f"/api/presence/me?household_id={A}", json={"state": "out"}, headers=as_(BRUNO))
    assert [e.data.state.value for e in cues(client.app_state.db)] == ["in", "out"]


def test_manual_body_cannot_name_another_resident_or_state(client):
    url = f"/api/presence/me?household_id={A}"
    for bad in (
        {"state": "in", "resident_id": str(fx.CARLA)},
        {"state": "uncertain"},
        {"state": "in", "source": "wifi"},
        {},
    ):
        assert client.put(url, json=bad, headers=as_(BRUNO)).status_code == 400
    assert cues(client.app_state.db) == []


def test_manual_cue_is_only_for_the_house_where_the_user_is_a_tenant(client):
    # Bruno é inquilino nas casas A e B: cada declaração fica na casa pedida
    client.put(f"/api/presence/me?household_id={B}", json={"state": "out"}, headers=as_(BRUNO))
    [ev] = cues(client.app_state.db)
    assert str(ev.household_id) == B and ev.data.resident_id == fx.BRUNO


# --- registo e revogação de telemóveis -----------------------------------------------------------


def test_register_returns_only_the_view_and_never_stores_the_mac(client):
    r = register(client, BRUNO, "2:0:0:AA:0:1", label="Telemóvel do B.")
    assert r.status_code == 201
    view = r.json()
    assert set(view) == {"id", "label", "wifi_opt_in", "consented_at", "revoked_at"}
    assert view["wifi_opt_in"] is True and view["revoked_at"] is None
    blob = dump_text(client.app_state.db).lower()
    for form in (MAC_BRUNO, MAC_BRUNO.replace(":", ""), "2:0:0:aa:0:1", "02-00-00-aa-00-01"):
        assert form not in blob
    assert match_key(SALT, MAC_BRUNO) in blob  # só o pseudónimo
    assert MAC_BRUNO not in r.text and match_key(SALT, MAC_BRUNO) not in r.text


def test_register_requires_explicit_consent_and_a_valid_address(client):
    url = f"/api/presence/devices?household_id={A}"
    ok = {"label": "T", "wifi_address": MAC_BRUNO}
    assert client.post(url, json={**ok, "consent": False}, headers=as_(BRUNO)).status_code == 400
    assert client.post(url, json=ok, headers=as_(BRUNO)).status_code == 400
    r = client.post(url, json={**ok, "wifi_address": "isto-nao-e", "consent": True},
                    headers=as_(BRUNO))  # fmt: skip
    assert code(r)[0] == 400
    assert MAC_BRUNO not in r.text
    assert client.get(url, headers=as_(BRUNO)).json() == []


def test_duplicates_and_limit(client):
    assert register(client, BRUNO, MAC_BRUNO).status_code == 201
    assert code(register(client, BRUNO, "2:0:0:aa:0:1")) == (409, "device_already_registered")
    assert code(register(client, CARLA, MAC_BRUNO)) == (409, "device_already_registered")
    for i in range(2, 6):
        assert register(client, BRUNO, f"02:00:00:cc:00:{i:02x}").status_code == 201
    assert code(register(client, BRUNO, "02:00:00:cc:00:ff")) == (409, "device_limit")


def test_registration_is_off_without_salt(client, monkeypatch):
    client.app_state.presence.salt = ""
    assert code(register(client, BRUNO, MAC_BRUNO)) == (503, "wifi_unconfigured")


def test_devices_are_private_to_their_owner(client):
    d = register(client, BRUNO, MAC_BRUNO).json()
    assert client.get(f"/api/presence/devices?household_id={A}", headers=as_(CARLA)).json() == []
    r = client.delete(f"/api/presence/devices/{d['id']}?household_id={A}", headers=as_(CARLA))
    assert code(r) == (404, "device_not_found")
    mine = client.get(f"/api/presence/devices?household_id={A}", headers=as_(BRUNO)).json()
    assert len(mine) == 1


def test_revoke_takes_effect_immediately_and_erases_the_key(client, clock):
    d = register(client, BRUNO, MAC_BRUNO).json()
    assert observe(client, MAC_BRUNO).status_code == 204
    assert len(cues(client.app_state.db, "wifi")) == 1
    r = client.delete(f"/api/presence/devices/{d['id']}?household_id={A}", headers=as_(BRUNO))
    assert r.status_code == 204
    clock.advance(hours=1)
    observe(client, MAC_BRUNO)
    assert len(cues(client.app_state.db, "wifi")) == 1  # nenhuma pista nova depois do opt-out
    assert match_key(SALT, MAC_BRUNO) not in dump_text(client.app_state.db)
    [view] = client.get(f"/api/presence/devices?household_id={A}", headers=as_(BRUNO)).json()
    assert view["wifi_opt_in"] is False and view["revoked_at"] is not None
    # idempotente, e o mesmo telemóvel pode voltar a registar-se (novo consentimento)
    assert (
        client.delete(
            f"/api/presence/devices/{d['id']}?household_id={A}", headers=as_(BRUNO)
        ).status_code
        == 204
    )
    assert register(client, BRUNO, MAC_BRUNO).status_code == 201


# --- pistas Wi-Fi (rota do varrimento no anfitrião) ----------------------------------------------


def test_ingest_needs_the_machine_token_and_the_ingest_mode(client, monkeypatch):
    body = {"keys": [match_key(SALT, MAC_BRUNO)]}
    url = "/api/presence/wifi/observations"
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers={"x-presence-token": "errado"}).status_code == 401
    assert client.post(url, json=body, headers=as_(BRUNO)).status_code == 401  # JWT não serve
    assert url not in client.get("/openapi.json").json()["paths"]
    from homemind.core.config import get_settings

    monkeypatch.setenv("PRESENCE_WIFI_MODE", "off")
    get_settings.cache_clear()
    assert client.post(url, json=body, headers=TOK).status_code == 404


def test_registered_phone_appearing_gives_one_wifi_in_cue(client, clock):
    register(client, BRUNO, MAC_BRUNO)
    assert observe(client, MAC_BRUNO, MAC_VISITA).status_code == 204
    [ev] = cues(client.app_state.db)
    assert ev.data.source.value == "wifi" and ev.data.state.value == "in"
    assert ev.data.resident_id == fx.BRUNO
    assert ev.provenance == Provenance(origin=Origin.real, kind=ValueKind.inferred)
    observe(client, MAC_BRUNO)  # logo a seguir: sem pista repetida
    assert len(cues(client.app_state.db)) == 1


def test_visitors_and_unregistered_devices_leave_no_trace(client):
    register(client, BRUNO, MAC_BRUNO)
    observe(client, MAC_VISITA, MAC_CARLA)  # Carla ainda não registou o telemóvel
    assert cues(client.app_state.db) == []
    blob = dump_text(client.app_state.db)
    for mac in (MAC_VISITA, MAC_CARLA):
        assert match_key(SALT, mac) not in blob and mac not in blob


def test_absence_never_generates_a_cue_and_rate_limits_apply(client, clock):
    register(client, BRUNO, MAC_BRUNO)
    observe(client, MAC_BRUNO)
    for _ in range(5):  # o telemóvel desaparece: nada é gravado, e muito menos `out`
        clock.advance(minutes=10)
        observe(client)
    assert [e.data.state.value for e in cues(client.app_state.db)] == ["in"]
    clock.advance(seconds=61)
    observe(client, MAC_BRUNO)  # voltou a aparecer
    assert len(cues(client.app_state.db)) == 2
    clock.advance(seconds=120)
    observe(client, MAC_BRUNO)  # ainda ligado: só renova a pista passado o intervalo de refresh
    assert len(cues(client.app_state.db)) == 2
    clock.advance(seconds=400)
    observe(client, MAC_BRUNO)
    assert len(cues(client.app_state.db)) == 3


def test_ended_membership_or_landlord_never_produce_cues(client, clock):
    register(client, BRUNO, MAC_BRUNO)
    clock.advance(days=400)  # a membership do Bruno ainda não tem fim; simular o fim
    client.app_state.db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status='ended', ends_on='2026-01-01', starts_on='2025-01-01'"
            " WHERE resident_id = ?", (str(fx.BRUNO),)
        )
    )  # fmt: skip
    observe(client, MAC_BRUNO)
    assert cues(client.app_state.db) == []


def test_nothing_sensitive_reaches_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    register(client, BRUNO, MAC_BRUNO)
    observe(client, MAC_BRUNO, MAC_VISITA)
    register(client, BRUNO, "isto-nao-e-um-mac")
    text = caplog.text
    for secret in (MAC_BRUNO, MAC_VISITA, MAC_BRUNO.replace(":", ""), SALT, TOKEN,
                   match_key(SALT, MAC_BRUNO)):  # fmt: skip
        assert secret not in text


# --- poller com scanner simulado -----------------------------------------------------------------


def test_poller_with_fake_scanner_is_simulated_and_failures_never_mean_out(world, caplog):
    caplog.set_level(logging.DEBUG)
    db = world.db
    asyncio.run(world.register_device(fx.HOUSEHOLD, fx.BRUNO, "T", MAC_BRUNO))
    scanner = FakeWifiScanner([MAC_BRUNO, MAC_VISITA])
    poller = WifiPoller(world, scanner, 30)
    assert asyncio.run(poller.run_once()) == 1
    [ev] = cues(db)
    assert ev.provenance == Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
    scanner.fail = True
    world.clock.advance(hours=2)
    assert asyncio.run(poller.run_once()) == 0  # varrimento falhado: nada, nunca `out`
    assert [e.data.state.value for e in cues(db)] == ["in"]
    assert MAC_BRUNO not in caplog.text and MAC_VISITA not in caplog.text


def test_simulated_cues_are_refused_in_a_real_household(world):
    asyncio.run(world.register_device(fx.HOUSEHOLD, fx.BRUNO, "T", MAC_BRUNO))
    world.db.run_sync(lambda c: c.execute("UPDATE household SET source_kind = 'real'"))
    poller = WifiPoller(world, FakeWifiScanner([MAC_BRUNO]), 30)
    assert asyncio.run(poller.run_once()) == 0
    assert cues(world.db) == []


# --- «estás em casa?» respondido na app ----------------------------------------------------------


def _ask(db, resident=fx.BRUNO, hid=fx.HOUSEHOLD):
    req = PresenceConfirmationRequest(
        id=stable_id("req", str(resident), str(NOW)),
        resident_id=resident,
        reason=UncertainReason.conflicting_cues,
        expires_at=NOW + timedelta(minutes=30),
    )
    db.run_sync(lambda c: repo.insert_confirmation(c, hid, req, NOW))
    return req


def _answer(req, action="in", by=fx.BRUNO, kind=RefType.presence_check, hid=fx.HOUSEHOLD, n="1"):
    return NotificationResponded(
        id=stable_id("resp", n),
        ts=NOW + timedelta(minutes=2),
        household_id=hid,
        provenance=Provenance(origin=Origin.simulated, kind=ValueKind.measured),
        data=NotificationRespondedData(
            response=NotificationResponse(
                notification_id=stable_id("notif", n),
                action_id=action,
                resident_id=by,
                responded_at=NOW + timedelta(minutes=2),
            ),
            ref=NotificationRef(type=kind, id=req.id),
        ),
    )


def _deliver(world, ev):
    bus = world.bus
    if "presence.answers" not in bus._subs:
        bus.subscribe("presence.answers", on_notification_responded,
                      types=["notification.responded"])  # fmt: skip
    world.db.run_sync(lambda c: append_event(c, ev))
    from homemind.core.events import load_events

    [stored] = [s for s in world.db.run_sync(lambda c: load_events(c)) if s.event.id == ev.id]
    return asyncio.run(bus.deliver("presence.answers", stored))


@pytest.mark.parametrize("action,state", [("in", "in"), ("out", "out")])
def test_answer_in_the_app_becomes_a_manual_cue_once(world, action, state):
    req = _ask(world.db)
    ev = _answer(req, action)
    assert _deliver(world, ev) is True
    [cue] = cues(world.db, "manual")
    assert cue.data.state.value == state and cue.data.resident_id == fx.BRUNO
    assert cue.provenance.origin is Origin.simulated  # herda a origem da resposta
    assert cue.correlation_id == ev.correlation_id
    assert _deliver(world, ev) is False  # entrega repetida: sem efeito
    assert len(cues(world.db)) == 1
    again = _answer(req, action, n="2")  # segunda resposta ao mesmo pedido: ignorada
    _deliver(world, again)
    assert len(cues(world.db)) == 1


@pytest.mark.parametrize(
    "kw",
    [
        {"by": fx.CARLA},  # responde outra pessoa
        {"action": "talvez"},  # ação fora de in/out
        {"kind": RefType.budget},  # não é um presence_check
    ],
)
def test_answers_that_do_not_match_a_request_are_ignored(world, kw):
    req = _ask(world.db)
    _deliver(world, _answer(req, **kw))
    assert cues(world.db) == []


def test_answer_without_a_request_or_for_another_household_is_ignored(world):
    req = _ask(world.db)
    ghost = req.model_copy(update={"id": stable_id("nao-existe")})
    _deliver(world, _answer(ghost))
    from homemind.features.households.tests.conftest import HOUSE_B

    _deliver(world, _answer(req, hid=HOUSE_B, n="3"))  # pedido é da casa A
    assert cues(world.db) == []


# --- os DOIS consentimentos do Wi-Fi -----------------------------------------------------------


@pytest.mark.parametrize(
    "wifi_opt_in,presence_opt_in,expected",
    [(True, True, 1), (True, False, 0), (False, True, 0), (False, False, 0)],
)
def test_wifi_cue_needs_both_consents(client, wifi_opt_in, presence_opt_in, expected):
    d = register(client, BRUNO, MAC_BRUNO).json()
    if not wifi_opt_in:
        client.delete(f"/api/presence/devices/{d['id']}?household_id={A}", headers=as_(BRUNO))
    set_presence_opt_in(client.app_state.db, fx.BRUNO, int(presence_opt_in))
    observe(client, MAC_BRUNO)
    assert len(cues(client.app_state.db, "wifi")) == expected


def test_revoking_presence_opt_in_stops_wifi_cues_at_once(client, clock):
    register(client, BRUNO, MAC_BRUNO)
    observe(client, MAC_BRUNO)
    set_presence_opt_in(client.app_state.db, fx.BRUNO, 0)
    clock.advance(hours=1)
    observe(client, MAC_BRUNO)
    assert len(cues(client.app_state.db, "wifi")) == 1


def test_collection_switch_off_disables_ingest(client, monkeypatch):
    from homemind.core.config import get_settings

    monkeypatch.setenv("PRESENCE_WIFI_COLLECTION_ENABLED", "false")
    get_settings.cache_clear()
    register(client, BRUNO, MAC_BRUNO)
    assert observe(client, MAC_BRUNO).status_code == 404
    assert cues(client.app_state.db) == []
