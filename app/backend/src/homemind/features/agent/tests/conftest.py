"""App real com base em memória, utilizadores simulados e relógio controlado.

Cópia da fixture de `features/households/tests/conftest.py` (uma feature não importa os testes de
outra). Diferença deliberada: `get_complete` é SEMPRE substituído, para que uma `NVIDIA_API_KEY`
do ambiente nunca chegue à rede num teste.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.common import stable_id
from homemind.core.access import get_clock
from homemind.features.agent.router import get_complete
from homemind.features.auth.service import User, current_user
from homemind.features.households.repo import (
    insert_household,
    insert_membership,
    insert_resident,
    insert_room,
    seed_demo,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
HOUSE_B = stable_id("household", "casa-b")
HOUSE_C = stable_id("household", "casa-c")  # casa REAL (AGENT-03: executor e diretório injetados)
ROOM_B1, ROOM_B2 = stable_id("room", "b1"), stable_id("room", "b2")
EVA, HUGO, FRED = (stable_id("resident", n) for n in ("eva", "hugo", "fred"))
GINA, HANA, IVO = (stable_id("resident", n) for n in ("gina", "hana", "ivo"))


def seed_two_houses(conn) -> None:
    """Casa A (demo: Ana, Bruno, Carla, Diogo, senhorio, operador) e casa B (Eva, Hugo, Fred).
    Bruno é também inquilino na casa B. A membership de Fred (casa B) já terminou."""
    seed_demo(conn)
    insert_household(
        conn,
        hh.Household(
            id=HOUSE_B,
            name="Casa B",
            settings=hh.HouseholdSettings(source_kind=hh.SourceKind.demo),
            created_at=fx.T0,
        ),
    )
    for rid, name in ((ROOM_B1, "Quarto 1"), (ROOM_B2, "Quarto 2")):
        insert_room(
            conn, hh.Room(id=rid, household_id=HOUSE_B, name=name, kind=hh.RoomKind.bedroom)
        )
    for rid, name, sub in (
        (EVA, "Eva", "sub-eva"),
        (HUGO, "Hugo", "sub-hugo"),
        (FRED, "Fred", "sub-fred"),
    ):
        insert_resident(conn, hh.Resident(id=rid, display_name=name, auth_subject=sub))
    start = date(2026, 9, 1)
    ten, act = hh.MembershipRole.tenant, hh.MembershipStatus.active
    for mid, res, role, room, status, ends in (
        (stable_id("membership", "eva"), EVA, ten, ROOM_B1, act, None),
        (stable_id("membership", "bruno-b"), fx.BRUNO, ten, ROOM_B2, act, None),
        (stable_id("membership", "hugo"), HUGO, hh.MembershipRole.landlord, None, act, None),
        (stable_id("membership", "fred"), FRED, ten, ROOM_B1, hh.MembershipStatus.ended,
         date(2026, 10, 1)),
    ):  # fmt: skip
        insert_membership(
            conn,
            hh.Membership(
                id=mid, household_id=HOUSE_B, resident_id=res, role=role, room_id=room,
                starts_on=start, ends_on=ends, status=status,
            ),
        )  # fmt: skip


def seed_real_house(conn) -> None:
    """Casa C, `source_kind='real'`: Gina e Hana (inquilinas) e Ivo (senhorio)."""
    insert_household(
        conn,
        hh.Household(
            id=HOUSE_C,
            name="Casa C",
            settings=hh.HouseholdSettings(source_kind=hh.SourceKind.real),
            created_at=fx.T0,
        ),
    )
    rooms = {GINA: stable_id("room", "c1"), HANA: stable_id("room", "c2")}
    for rid, name in ((rooms[GINA], "Quarto 1"), (rooms[HANA], "Quarto 2")):
        insert_room(
            conn, hh.Room(id=rid, household_id=HOUSE_C, name=name, kind=hh.RoomKind.bedroom)
        )
    for rid, name in ((GINA, "Gina"), (HANA, "Hana"), (IVO, "Ivo")):
        insert_resident(
            conn, hh.Resident(id=rid, display_name=name, auth_subject=f"sub-{name.lower()}")
        )
    for rid, role, room in (
        (GINA, hh.MembershipRole.tenant, rooms[GINA]),
        (HANA, hh.MembershipRole.tenant, rooms[HANA]),
        (IVO, hh.MembershipRole.landlord, None),
    ):
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", "c", str(rid)), household_id=HOUSE_C, resident_id=rid,
                role=role, room_id=room, starts_on=date(2026, 9, 1),
                status=hh.MembershipStatus.active,
            ),
        )  # fmt: skip


class LlmSwitch:
    """O que `get_complete` devolve neste teste (`None` por omissão: sem LLM)."""

    def __init__(self):
        self.complete = None


@pytest.fixture
def llm():
    return LlmSwitch()


@pytest.fixture
def now():
    return {"value": NOW}


@pytest.fixture
def app(now, llm):
    from homemind.main import app as real_app

    def fake_user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(sub=sub)

    real_app.dependency_overrides[current_user] = fake_user
    real_app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    real_app.dependency_overrides[get_complete] = lambda: llm.complete  # nunca o real
    with TestClient(real_app):
        real_app.state.db.run_sync(seed_two_houses)
        yield real_app
    real_app.dependency_overrides.clear()


@pytest.fixture
def real_house(app):
    app.state.db.run_sync(seed_real_house)
    return HOUSE_C


@pytest.fixture
def client(app):
    return TestClient(app)


def as_(sub: str) -> dict[str, str]:
    return {"x-test-sub": sub}
