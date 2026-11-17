"""PRES-04: a fusão ligada ao barramento (pistas, porta, aparelho, resposta) e à API."""

import time
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, new_id, stable_id
from homemind.contracts.domain_events import (
    EnergyConsumptionDetected,
    NotificationResponded,
    NotificationRespondedData,
    PresenceCueRecorded,
    PresenceDoorCrossed,
)
from homemind.contracts.notification import NotificationRef, NotificationResponse, RefType
from homemind.contracts.presence import (
    DoorCrossed,
    DoorDirection,
    PresenceEvent,
    PresenceSource,
    PresenceState,
)
from homemind.core.events import load_events
from homemind.features.presence.tests.conftest import (
    MAC_BRUNO,
    SALT,
    TOKEN,
    A,
    as_,
    cues,
    set_presence_opt_in,
)
from homemind.features.presence.wifi import match_key

BRUNO, ANA, CARLA, LANDLORD, OPERATOR = (
    "sub-bruno", "sub-ana", "sub-carla", "sub-senhorio", "sub-operador",
)  # fmt: skip
SIM = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
MEASURED = Provenance(origin=Origin.real, kind=ValueKind.measured)


def events(client, *types):
    db = client.app_state.db
    return [s.event for s in db.run_sync(lambda c: load_events(c, types=list(types)))]


def wait_for(cond, what="condição", timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"tempo esgotado: {what}")


def settle(client):
    """Espera que os consumidores tenham tratado tudo o que está no registo."""
    db = client.app_state.db

    def pending() -> int:
        return db.run_sync(
            lambda c: c.execute(
                "SELECT COUNT(*) FROM domain_event d WHERE d.type IN"
                " ('presence.cue_recorded','presence.door_crossed','energy.consumption_detected',"
                "'notification.responded') AND NOT EXISTS (SELECT 1 FROM processed_event p"
                " WHERE p.event_id = d.id AND p.consumer IN"
                " ('presence.fusion','presence.appliance','presence.answers'))"
            ).fetchone()[0]
        )

    wait_for(lambda: pending() == 0, "consumidores")
    time.sleep(0.05)


def tick(client):
    client.portal.call(client.app_state.presence.tick)
    settle(client)


RESIDENT = {BRUNO: fx.BRUNO, CARLA: fx.CARLA, ANA: fx.ANA}


def put_me(client, sub, state):
    """Pista `manual` (a única origem é a resposta a «estás em casa?»; aqui injetada direto)."""
    clock = client.clock
    rid = RESIDENT[sub]
    ev = PresenceCueRecorded(
        ts=clock.now,
        household_id=fx.HOUSEHOLD,
        provenance=MEASURED,
        data=PresenceEvent(
            id=new_id(),
            household_id=fx.HOUSEHOLD,
            resident_id=rid,
            ts=clock.now,
            state=PresenceState(state),
            source=PresenceSource.manual,
            confidence=1.0,
            provenance=MEASURED,
        ),
    )
    client.app_state.bus.publish_threadsafe(ev)


def get_own(client, sub, household=A):
    r = client.get(f"/api/presence?household_id={household}", headers=as_(sub))
    assert r.status_code == 200, r.text
    return r.json()


def door(client, clock, direction, conf=0.9):
    client.app_state.bus.publish_threadsafe(
        PresenceDoorCrossed(
            ts=clock.now,
            household_id=fx.HOUSEHOLD,
            provenance=SIM,
            data=DoorCrossed(
                ts=clock.now, direction=DoorDirection(direction), confidence=conf, provenance=SIM
            ),
        )
    )
    settle(client)


def consumption_started(client, clock, *, started_ago, cid="aquecedor", owner=fx.BRUNO):
    d = fx.consumption().model_copy(
        update={
            "id": stable_id("consumption", cid),
            "started_at": clock.now - started_ago,
            "appliance_owner_resident_id": owner,
        }
    )
    client.app_state.bus.publish_threadsafe(
        EnergyConsumptionDetected(ts=clock.now, household_id=fx.HOUSEHOLD, provenance=SIM, data=d)
    )
    settle(client)
    return d


def state_of(client, sub=BRUNO):
    own = get_own(client, sub)
    return own["state"], own.get("reason"), own


def changes(client):
    return [e.data.state.value for e in events(client, "presence.changed")]


# --- em casa, a dormir, fora -----------------------------------------------------------------


def test_answer_yes_is_fused_and_published_once(client, clock):
    put_me(client, BRUNO, "in")
    settle(client)
    assert state_of(client)[0] == "in" and state_of(client)[2]["sources"] == ["manual"]
    assert changes(client) == ["in"]
    put_me(client, BRUNO, "in")  # repetir não muda o estado: nada a publicar
    settle(client)
    assert changes(client) == ["in"]


def test_sleeping_phone_10_minutes_without_the_door_stays_in(client, clock):
    client.post(
        f"/api/presence/devices?household_id={A}",
        json={"label": "T", "wifi_address": MAC_BRUNO, "consent": True},
        headers=as_(BRUNO),
    )
    client.post(
        "/api/presence/wifi/observations",
        json={"keys": [match_key(SALT, MAC_BRUNO)]},
        headers={"x-presence-token": TOKEN},
    )
    settle(client)
    assert state_of(client)[0] == "in"
    clock.advance(minutes=10)  # o telemóvel adormeceu: nenhuma pista, nenhuma passagem
    tick(client)
    assert state_of(client)[0] == "in"
    assert changes(client) == ["in"]


def test_door_exit_then_tolerance_makes_out_and_publishes_changed(client, clock):
    put_me(client, BRUNO, "in")
    clock.advance(minutes=5)
    door(client, clock, "out")
    clock.advance(minutes=20)
    tick(client)
    assert state_of(client)[0] == "in"  # 20 min depois da saída: ainda dentro da tolerância
    clock.advance(minutes=6)
    tick(client)
    state, reason, own = state_of(client)
    assert (state, reason) == ("out", None) and own["sources"] == ["camera_door"]
    assert changes(client) == ["in", "out"]
    tick(client)  # sem mudança: não republica
    assert changes(client) == ["in", "out"]


def test_exit_by_someone_else_is_refuted_by_the_residents_own_cue(client, clock):
    put_me(client, BRUNO, "in")
    clock.advance(minutes=5)
    door(client, clock, "out")
    clock.advance(minutes=10)
    put_me(client, BRUNO, "in")  # «cheguei/continuo aqui»
    clock.advance(minutes=60)
    tick(client)
    assert state_of(client)[0] == "in" and changes(client) == ["in"]


def test_answer_no_to_the_question_is_out_immediately(client, clock):
    put_me(client, BRUNO, "in")
    settle(client)
    put_me(client, BRUNO, "out")
    settle(client)
    assert state_of(client)[0] == "out"
    assert changes(client) == ["in", "out"]


# --- aparelho ---------------------------------------------------------------------------------


def test_a_pc_that_was_already_on_does_not_prove_the_resident_is_home(client, clock):
    consumption_started(client, clock, started_ago=timedelta(hours=3))
    assert cues(client.app_state.db) == []
    state, reason, own = state_of(client)
    assert (state, reason) == ("uncertain", "no_recent_cues") and own["sources"] == []
    assert events(client, "presence.changed") == []
    # nem sequer mantém «em casa» quem já estava fora
    put_me(client, BRUNO, "out")
    consumption_started(client, clock, started_ago=timedelta(hours=4), cid="pc")
    settle(client)
    assert state_of(client)[0] == "out" and len(cues(client.app_state.db)) == 1


def test_a_personal_appliance_turning_on_proves_in_once(client, clock):
    d = consumption_started(client, clock, started_ago=timedelta(seconds=20))
    [cue] = cues(client.app_state.db, "appliance")
    assert cue.data.consumption_event_id == d.id and cue.data.resident_id == fx.BRUNO
    assert cue.provenance == SIM  # herda a origem do consumo
    assert state_of(client)[0] == "in"
    client.app_state.bus.publish_threadsafe(  # o mesmo consumo notificado outra vez
        EnergyConsumptionDetected(
            ts=clock.now + timedelta(seconds=30),
            household_id=fx.HOUSEHOLD,
            provenance=SIM,
            data=d,
        )
    )
    settle(client)
    assert len(cues(client.app_state.db, "appliance")) == 1


def test_appliance_without_owner_or_of_a_non_tenant_is_ignored(client, clock):
    consumption_started(client, clock, started_ago=timedelta(seconds=5), owner=None, cid="x")
    consumption_started(client, clock, started_ago=timedelta(seconds=5), owner=fx.LANDLORD, cid="y")
    assert cues(client.app_state.db) == []


# --- contradição e pergunta -------------------------------------------------------------------


def _conflict(client, clock):
    put_me(client, BRUNO, "out")
    settle(client)
    clock.advance(minutes=20)
    consumption_started(client, clock, started_ago=timedelta(seconds=5))


def test_contradiction_is_uncertain_and_asks_once_per_cooldown(client, clock):
    _conflict(client, clock)
    state, reason, own = state_of(client)
    assert (state, reason) == ("uncertain", "conflicting_cues")
    assert own["sources"] == ["appliance"]
    [req] = events(client, "presence.confirmation_needed")
    assert req.data.resident_id == fx.BRUNO and req.data.reason.value == "conflicting_cues"
    assert req.data.expires_at == req.ts + timedelta(minutes=30)
    assert changes(client) == ["out", "uncertain"]
    clock.advance(minutes=5)
    consumption_started(client, clock, started_ago=timedelta(seconds=5), cid="outra")
    assert len(events(client, "presence.confirmation_needed")) == 1  # sem insistir
    clock.advance(minutes=31)
    tick(client)
    assert len(events(client, "presence.confirmation_needed")) == 2  # volta a perguntar


def test_the_request_carries_no_accusation_images_or_foreign_data(client, clock):
    _conflict(client, clock)
    [req] = events(client, "presence.confirmation_needed")
    assert set(req.data.model_dump()) == {"id", "resident_id", "reason", "expires_at"}


def test_answering_the_question_resolves_the_doubt(client, clock):
    _conflict(client, clock)
    [req] = events(client, "presence.confirmation_needed")
    clock.advance(minutes=2)
    client.app_state.bus.publish_threadsafe(
        NotificationResponded(
            ts=clock.now,
            household_id=fx.HOUSEHOLD,
            provenance=SIM,
            data=NotificationRespondedData(
                response=NotificationResponse(
                    notification_id=stable_id("n", "1"),
                    action_id="in",
                    resident_id=fx.BRUNO,
                    responded_at=clock.now,
                ),
                ref=NotificationRef(type=RefType.presence_check, id=req.data.id),
            ),
        )
    )
    settle(client)
    wait_for(lambda: state_of(client)[0] == "in", "estado in depois da resposta")
    assert changes(client)[-1] == "in"


def test_an_entry_through_the_door_explains_the_return_without_asking(client, clock):
    put_me(client, BRUNO, "out")
    clock.advance(minutes=10)
    door(client, clock, "in")
    clock.advance(seconds=30)
    consumption_started(client, clock, started_ago=timedelta(seconds=5))
    assert state_of(client)[0] == "in"
    assert events(client, "presence.confirmation_needed") == []


# --- falhas nunca dão «fora» ---------------------------------------------------------------------


def test_wifi_down_after_an_exit_is_a_question_never_a_wrong_out(client, clock):
    client.post(
        f"/api/presence/devices?household_id={A}",
        json={"label": "T", "wifi_address": MAC_BRUNO, "consent": True},
        headers=as_(BRUNO),
    )
    client.post(
        "/api/presence/wifi/observations",
        json={"keys": [match_key(SALT, MAC_BRUNO)]},
        headers={"x-presence-token": TOKEN},
    )
    settle(client)
    clock.advance(minutes=5)
    door(client, clock, "out")
    clock.advance(minutes=40)  # o varrimento deixou de correr há 45 min
    tick(client)
    state, reason, _ = state_of(client)
    assert (state, reason) == ("uncertain", "no_recent_cues")
    assert "out" not in changes(client)
    assert len(events(client, "presence.confirmation_needed")) == 1


def test_door_events_alone_never_create_a_state(client, clock):
    door(client, clock, "in")
    door(client, clock, "out")
    clock.advance(hours=2)
    tick(client)
    assert events(client, "presence.changed") == []
    assert state_of(client)[0] == "uncertain"


# --- API ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_landlord_and_operator_get_403_on_the_state_route(client, sub):
    r = client.get(f"/api/presence?household_id={A}", headers=as_(sub))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"


def test_outsiders_and_anonymous(client):
    assert client.get(f"/api/presence?household_id={A}", headers=as_("sub-eva")).status_code == 404
    assert client.get(f"/api/presence?household_id={A}").status_code == 401


def test_each_resident_sees_only_their_own_state_even_if_a_colleague_opted_in(client, clock):
    put_me(client, BRUNO, "in")
    set_presence_opt_in(client.app_state.db, fx.CARLA, 1)
    put_me(client, CARLA, "out")
    settle(client)
    set_presence_opt_in(client.app_state.db, fx.BRUNO, 1)
    for sub, rid, st in ((ANA, fx.ANA, "uncertain"), (BRUNO, fx.BRUNO, "in"),
                         (CARLA, fx.CARLA, "out")):  # fmt: skip
        own = get_own(client, sub)
        assert isinstance(own, dict) and own["resident_id"] == str(rid) and own["state"] == st


def test_state_response_has_no_ids_of_cues_nor_images(client, clock):
    put_me(client, BRUNO, "in")
    p = get_own(client, BRUNO)
    assert set(p) == {"resident_id", "state", "since", "confidence", "provenance", "sources",
                      "reason"}  # fmt: skip


# --- sem presence_opt_in nada se grava ---


def test_without_presence_opt_in_no_state_is_stored_or_published(client, clock):
    put_me(client, CARLA, "in")  # Carla não tem opt-in
    consumption_started(
        client, clock, started_ago=timedelta(seconds=5), owner=fx.CARLA, cid="carla"
    )
    door(client, clock, "out")
    clock.advance(hours=1)
    tick(client)
    db = client.app_state.db
    assert (
        db.run_sync(lambda c: c.execute("SELECT COUNT(*) FROM presence_state").fetchone()[0]) == 0
    )
    assert events(client, "presence.changed") == []
    assert [c.data.source.value for c in cues(db)] == ["manual"]  # só o que injetámos à mão
