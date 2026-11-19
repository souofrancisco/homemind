"""Fixtures da `safety`: base SQLite em memória (serviço) e a app real com utilizadores simulados
e relógio controlado (rotas). Nunca hardware, rede, LLM nem MCP. Casa A é a demo (Ana, Bruno,
Carla, Diogo, senhorio, operador) e casa B é de outra pessoa (Eva, inquilina)."""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import household as hh
from homemind.contracts.common import stable_id
from homemind.core.access import get_clock
from homemind.core.db import Database, migrate
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
HOUSE_REAL = stable_id("household", "casa-real")
EVA = stable_id("resident", "eva")


def seed_houses(conn) -> None:
    seed_demo(conn)
    for house, kind, name in (
        (HOUSE_B, hh.SourceKind.demo, "Casa B"),
        (HOUSE_REAL, hh.SourceKind.real, "Casa real"),
    ):
        insert_household(
            conn,
            hh.Household(
                id=house, name=name, settings=hh.HouseholdSettings(source_kind=kind),
                created_at=NOW,
            ),
        )  # fmt: skip
    room = stable_id("room", "b1")
    insert_room(
        conn, hh.Room(id=room, household_id=HOUSE_B, name="Quarto 1", kind=hh.RoomKind.bedroom)
    )
    insert_resident(conn, hh.Resident(id=EVA, display_name="Eva", auth_subject="sub-eva"))
    insert_membership(
        conn,
        hh.Membership(
            id=stable_id("membership", "b"), household_id=HOUSE_B, resident_id=EVA,
            role=hh.MembershipRole.tenant, room_id=room, starts_on=date(2026, 9, 1),
            status=hh.MembershipStatus.active,
        ),
    )  # fmt: skip
    # uma inquilina também na casa real (para provar que o painel simulado lá é indisponível)
    real_room = stable_id("room", "real1")
    insert_room(
        conn,
        hh.Room(id=real_room, household_id=HOUSE_REAL, name="Q1", kind=hh.RoomKind.bedroom),
    )
    rid = stable_id("resident", "rita")
    insert_resident(conn, hh.Resident(id=rid, display_name="Rita", auth_subject="sub-rita"))
    insert_membership(
        conn,
        hh.Membership(
            id=stable_id("membership", "real"), household_id=HOUSE_REAL, resident_id=rid,
            role=hh.MembershipRole.tenant, room_id=real_room, starts_on=date(2026, 9, 1),
            status=hh.MembershipStatus.active,
        ),
    )  # fmt: skip


@pytest.fixture
def db():
    database = Database(":memory:")
    database.open()
    migrate(database)
    database.run_sync(seed_houses)
    yield database
    database.close()


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
        return User(sub=sub)

    real_app.dependency_overrides[current_user] = fake_user
    real_app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    with TestClient(real_app):
        real_app.state.db.run_sync(seed_houses)
        yield real_app
    real_app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def as_(sub: str) -> dict[str, str]:
    return {"x-test-sub": sub}
