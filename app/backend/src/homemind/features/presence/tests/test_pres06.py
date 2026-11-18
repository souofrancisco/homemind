"""PRES-06: casa candidata a vazia = contagem da porta fiável a 0 (a mesma da PRES-05, uma só
fonte de verdade para o cartão e para o evento). Relógio simulado; nunca arma nada."""

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin
from homemind.contracts.presence import OccupancyState
from homemind.features.presence import router as presence_router
from homemind.features.presence.occupancy import Residents, compute_occupancy
from homemind.features.presence.tests.conftest import A, as_, set_presence_opt_in
from homemind.features.presence.tests.test_pres04 import (
    BRUNO,
    LANDLORD,
    OPERATOR,
    door,
    events,
    put_me,
    settle,
    tick,
)
from homemind.features.presence.tests.test_pres05 import NOW, crossing, seq

# --- lógica pura -------------------------------------------------------------------------------


NOBODY = Residents(home=0, unknown=0)


def occ(doors, residents=NOBODY, *, camera_ok=True, empty_since=None):
    return compute_occupancy(
        doors, residents, NOW, camera_ok=camera_ok, camera_origin=Origin.simulated,
        empty_since=empty_since,
    )  # fmt: skip


def test_entries_and_exits_down_to_zero_with_nobody_home_is_empty():
    o = occ(seq("in", "in", "out", "out"))
    assert (o.state, o.people_inside, o.visitors, o.residents_home) == (
        OccupancyState.likely_empty, 0, 0, 0,
    )  # fmt: skip


def test_residents_without_opt_in_do_not_block_the_door_decides():
    assert occ(seq("in", "out"), Residents(home=0, unknown=4)).state is OccupancyState.likely_empty


def test_lost_entry_is_uncertain_never_empty():
    assert occ(seq("in", "out", "out")).state is OccupancyState.uncertain


def test_door_zero_but_a_phone_at_home_is_uncertain():
    o = occ(seq("in", "out"), Residents(home=1, unknown=0))
    assert o.state is OccupancyState.uncertain and o.people_inside is None


def test_stopped_camera_is_uncertain_never_empty_even_if_it_was():
    assert occ(seq("in", "out"), camera_ok=False).state is OccupancyState.uncertain
    assert occ([], camera_ok=False, empty_since=NOW).state is OccupancyState.uncertain


def test_no_passages_never_invent_empty():
    assert occ([]).state is OccupancyState.uncertain


def test_reliable_zero_is_kept_without_passages_but_not_with_a_phone_or_a_new_entry():
    assert occ([], empty_since=NOW).state is OccupancyState.likely_empty
    assert occ([], Residents(home=1, unknown=0), empty_since=NOW).state is OccupancyState.uncertain
    o = occ([crossing("in")], empty_since=NOW)  # entrou depois: ocupada
    assert (o.state, o.people_inside) == (OccupancyState.occupied, 1)


# --- com o barramento e a API ------------------------------------------------------------------


@pytest.fixture
def camera(monkeypatch):
    class Fonte:
        camara_ok = True

    monkeypatch.setattr(presence_router.video, "fonte_atual", lambda: Fonte())


def card(client, sub=BRUNO):
    r = client.get(f"/api/presence/occupancy?household_id={A}", headers=as_(sub))
    assert r.status_code == 200, r.text
    return r.json()


def states(client):
    return [e.data.state.value for e in events(client, "presence.occupancy_changed")]


def test_passages_to_zero_publish_empty_once_and_the_card_agrees(client, camera):
    door(client, client.clock, "in")
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    assert states(client) == ["occupied"]
    door(client, client.clock, "out")
    assert states(client) == ["occupied", "likely_empty"]
    assert card(client)["state"] == "likely_empty"
    tick(client)
    tick(client)
    assert states(client) == ["occupied", "likely_empty"]  # sem repetição
    last = events(client, "presence.occupancy_changed")[-1].data
    assert (last.people_inside, last.visitors, last.residents_home) == (0, 0, 0)


def test_entry_after_empty_is_occupied_and_card_agrees(client, camera):
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    door(client, client.clock, "in")
    assert states(client) == ["occupied", "likely_empty", "occupied"]
    assert card(client)["state"] == "occupied"


def test_lost_entry_is_uncertain_and_publishes_no_empty(client, camera):
    door(client, client.clock, "out")
    tick(client)
    assert "likely_empty" not in states(client) and card(client)["state"] == "uncertain"


def test_door_zero_with_a_resident_phone_home_is_uncertain(client, camera):
    set_presence_opt_in(client.app_state.db, fx.BRUNO, 1)
    put_me(client, BRUNO, "in")
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    settle(client)
    assert "likely_empty" not in states(client)
    assert card(client)["state"] == "uncertain"


def test_stopped_camera_is_never_empty(client):  # sem a fixture `camera`: fonte inativa
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    tick(client)
    assert "likely_empty" not in states(client) and card(client)["state"] == "uncertain"


def test_empty_house_over_a_weekend_stays_empty_while_the_camera_is_on(client, camera):
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    for _ in range(3):
        client.clock.advance(hours=20)  # 60 h sem passagens: a janela de 24 h já não as vê
        tick(client)
    assert card(client)["state"] == "likely_empty"
    assert states(client) == ["occupied", "likely_empty"]
    door(client, client.clock, "in")
    assert card(client)["state"] == "occupied"


def test_weekend_empty_is_lost_if_the_camera_stops(client, monkeypatch):
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    client.clock.advance(hours=30)
    tick(client)
    assert card(client)["state"] == "uncertain"  # sem câmara ativa (nenhuma fonte): nunca vazia


def test_occupancy_event_and_card_have_no_identity_and_nothing_physical(client, camera):
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    (*_, ev) = events(client, "presence.occupancy_changed")
    assert set(ev.data.model_dump()) == {
        "ts", "state", "people_inside", "visitors", "residents_home", "provenance",
    }  # fmt: skip
    assert events(client, "safety.alert_raised") == []


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_landlord_and_operator_never_see_the_empty_house(client, camera, sub):
    door(client, client.clock, "in")
    door(client, client.clock, "out")
    r = client.get(f"/api/presence/occupancy?household_id={A}", headers=as_(sub))
    assert r.status_code == 403
