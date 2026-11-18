"""PRES-05: ocupação agregada e visitas só como número. Relógio simulado, sem câmara real."""

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, new_id
from homemind.contracts.domain_events import PresenceCueRecorded
from homemind.contracts.presence import (
    DoorCrossed,
    DoorDirection,
    OccupancyState,
    PresenceEvent,
    PresenceSource,
    PresenceState,
)
from homemind.features.presence import router as presence_router
from homemind.features.presence.occupancy import (
    MAX_PEOPLE,
    Residents,
    compute_occupancy,
    door_balance,
)
from homemind.features.presence.tests.conftest import A, B, Clock, as_, set_presence_opt_in
from homemind.features.presence.tests.test_pres04 import (
    BRUNO,
    CARLA,
    LANDLORD,
    OPERATOR,
    door,
    put_me,
    settle,
)

SIM = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
REAL = Provenance(origin=Origin.real, kind=ValueKind.inferred)
NOW = Clock().now
ALL_KNOWN = Residents(home=0, unknown=0)


def crossing(direction: str, prov: Provenance = SIM) -> DoorCrossed:
    return DoorCrossed(ts=NOW, direction=DoorDirection(direction), confidence=0.9, provenance=prov)


def seq(*dirs: str, prov: Provenance = SIM) -> list[DoorCrossed]:
    return [crossing(d, prov) for d in dirs]


def occ(doors, residents=ALL_KNOWN, *, camera_ok=True, origin=Origin.simulated):
    return compute_occupancy(doors, residents, NOW, camera_ok=camera_ok, camera_origin=origin)


# --- lógica pura -------------------------------------------------------------------------------


def test_balance_counts_entries_minus_exits():
    assert door_balance(seq("in", "in", "out")) == (1, False)


def test_a_missed_entry_never_makes_the_count_negative():
    """Bug-alvo: «saiu» sem «entrou» não pode dar -1 nem 0 «certo»: reinicia e marca desync."""
    assert door_balance(seq("out")) == (0, True)
    assert door_balance(seq("out", "out", "in")) == (1, True)


def test_visitors_are_people_inside_minus_residents_home():
    o = occ(seq("in", "in", "in"), Residents(home=2, unknown=0))
    assert (o.state, o.people_inside, o.visitors, o.residents_home) == (
        OccupancyState.occupied, 3, 1, 2,
    )  # fmt: skip


def test_unknown_residents_make_the_visitor_count_unknown():
    o = occ(seq("in", "in"), Residents(home=1, unknown=1))
    assert (o.people_inside, o.visitors) == (2, None)


def test_a_visit_that_leaves_goes_back_to_zero_visitors():
    o = occ(seq("in", "in", "out"), Residents(home=1, unknown=0))
    assert (o.people_inside, o.visitors) == (1, 0)


def test_no_door_events_is_uncertain_not_empty():
    o = occ([])
    assert o.state is OccupancyState.uncertain and o.people_inside is None


def test_camera_failure_is_uncertain_even_with_events():
    o = occ(seq("in"), camera_ok=False)
    assert (o.state, o.people_inside, o.visitors) == (OccupancyState.uncertain, None, None)


def test_lost_entry_event_after_reset_is_uncertain():
    o = occ(seq("out"))
    assert (o.state, o.people_inside) == (OccupancyState.uncertain, None)


def test_door_count_below_residents_home_is_a_divergence():
    o = occ(seq("in"), Residents(home=2, unknown=0))
    assert (o.state, o.people_inside, o.visitors, o.residents_home) == (
        OccupancyState.uncertain, None, None, 2,
    )  # fmt: skip


def test_incomplete_exits_beyond_a_plausible_count_are_uncertain():
    o = occ(seq(*["in"] * (MAX_PEOPLE + 1)))
    assert o.state is OccupancyState.uncertain and o.people_inside is None


def test_zero_on_the_door_is_never_likely_empty():
    o = occ(seq("in", "out"))
    assert (o.state, o.people_inside, o.visitors) == (OccupancyState.uncertain, 0, 0)
    assert o.state is not OccupancyState.likely_empty


def test_provenance_is_simulated_when_the_camera_or_any_event_is():
    assert occ(seq("in", prov=REAL), origin=Origin.simulated).provenance.origin is (
        Origin.simulated
    )
    assert occ(seq("in", prov=SIM), origin=Origin.real).provenance.origin is Origin.simulated
    assert occ(seq("in", prov=REAL), origin=Origin.real).provenance.origin is Origin.real


def test_occupancy_exposes_no_identity_fields():
    assert set(occ(seq("in")).model_dump()) == {
        "ts", "state", "people_inside", "visitors", "residents_home", "provenance",
    }  # fmt: skip


# --- API: papel × rota, ligada ao registo da porta -----------------------------------------------


@pytest.fixture
def camera(monkeypatch):
    class Fonte:
        camara_ok = True

    monkeypatch.setattr(presence_router.video, "fonte_atual", lambda: Fonte())


def occupancy(client, sub, household=A):
    return client.get(f"/api/presence/occupancy?household_id={household}", headers=as_(sub))


def opt_in_everyone(client):
    for rid in (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO):
        set_presence_opt_in(client.app_state.db, rid, 1)


def test_tenant_sees_aggregate_numbers_only(client, camera):
    for _ in range(2):
        door(client, client.clock, "in")
    body = occupancy(client, BRUNO).json()
    assert set(body) == {"ts", "state", "people_inside", "visitors", "residents_home", "provenance"}
    assert body["people_inside"] == 2 and body["state"] == "occupied"
    assert body["provenance"]["origin"] == "simulated"


def test_unknown_residents_hide_the_visitor_count_and_create_no_individual_trail(client, camera):
    opt_in_everyone(client)
    put_me(client, BRUNO, "in")
    settle(client)
    for _ in range(2):  # o Bruno e uma visita entram pela porta
        door(client, client.clock, "in")
        client.clock.advance(seconds=5)
    body = occupancy(client, CARLA).json()
    assert (body["people_inside"], body["residents_home"], body["visitors"]) == (2, 1, None)
    # Carla, Ana e Diogo têm opt-in mas nenhum estado: desconhecidos, logo visitas desconhecidas.
    types = client.app_state.db.run_sync(
        lambda c: [r[0] for r in c.execute("SELECT DISTINCT type FROM domain_event")]
    )
    assert not any(t.startswith(("billing.", "notification")) for t in types)


def test_visitors_known_when_every_resident_is_known(client, camera):
    opt_in_everyone(client)
    for sub in (BRUNO, CARLA):
        put_me(client, sub, "in")
    for rid, state in ((fx.ANA, "out"), (fx.DIOGO, "out")):
        ev = PresenceEvent(
            id=new_id(), household_id=fx.HOUSEHOLD, resident_id=rid, ts=client.clock.now,
            state=PresenceState(state), source=PresenceSource.manual, confidence=1.0,
            provenance=REAL,
        )  # fmt: skip
        client.app_state.bus.publish_threadsafe(
            PresenceCueRecorded(
                ts=client.clock.now, household_id=fx.HOUSEHOLD, provenance=REAL, data=ev
            )
        )
    settle(client)
    for _ in range(3):
        door(client, client.clock, "in")
        client.clock.advance(seconds=5)
    body = occupancy(client, BRUNO).json()
    assert (body["people_inside"], body["residents_home"], body["visitors"]) == (3, 2, 1)


def test_exit_without_entry_is_uncertain_over_the_api(client, camera):
    door(client, client.clock, "out")
    body = occupancy(client, BRUNO).json()
    assert body["state"] == "uncertain" and body["people_inside"] is None


def test_old_entries_leave_the_window(client, camera):
    door(client, client.clock, "in")
    client.clock.advance(hours=25)
    assert occupancy(client, BRUNO).json()["people_inside"] is None


def test_camera_down_is_uncertain_over_the_api(client):
    door(client, client.clock, "in")  # sem fonte de vídeo no teste: câmara não está ok
    body = occupancy(client, BRUNO).json()
    assert body["state"] == "uncertain" and body["people_inside"] is None


@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_landlord_and_operator_get_403(client, camera, sub):
    door(client, client.clock, "in")
    r = occupancy(client, sub)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"


def test_other_house_and_anonymous_are_refused(client, camera):
    assert occupancy(client, CARLA, B).status_code == 404
    assert client.get(f"/api/presence/occupancy?household_id={A}").status_code == 401
