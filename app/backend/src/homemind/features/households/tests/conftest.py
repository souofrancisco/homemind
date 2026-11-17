"""App real com base em memória, utilizadores simulados (sem Authentik) e relógio controlado."""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.common import stable_id
from homemind.core.access import get_clock
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
ROOM_B1, ROOM_B2 = stable_id("room", "b1"), stable_id("room", "b2")
EVA, HUGO, FRED = (stable_id("resident", n) for n in ("eva", "hugo", "fred"))
M_EVA = stable_id("membership", "eva")
M_BRUNO_B = stable_id("membership", "bruno-b")
M_FRED = stable_id("membership", "fred")


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
        (M_EVA, EVA, ten, ROOM_B1, act, None),
        (M_BRUNO_B, fx.BRUNO, ten, ROOM_B2, act, None),
        (stable_id("membership", "hugo"), HUGO, hh.MembershipRole.landlord, None, act, None),
        (M_FRED, FRED, ten, ROOM_B1, hh.MembershipStatus.ended, date(2026, 10, 1)),
    ):
        insert_membership(
            conn,
            hh.Membership(
                id=mid, household_id=HOUSE_B, resident_id=res, role=role, room_id=room,
                starts_on=start, ends_on=ends, status=status,
            ),
        )  # fmt: skip


@pytest.fixture
def now():
    return {"value": NOW}


@pytest.fixture
def app(now):
    from homemind.main import app as real_app

    def fake_user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(
            sub=sub,
            email=request.headers.get("x-test-email"),
            email_verified=request.headers.get("x-test-verified") == "true",
        )

    real_app.dependency_overrides[current_user] = fake_user
    real_app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    with TestClient(real_app):  # corre o lifespan (base em memória, migrações)
        real_app.state.db.run_sync(seed_two_houses)
        yield real_app
    real_app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def as_(sub: str) -> dict[str, str]:
    return {"x-test-sub": sub}
