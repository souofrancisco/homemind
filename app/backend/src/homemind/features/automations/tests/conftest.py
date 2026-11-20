"""Fixtures da feature `automations`: base SQLite em memória (serviço) e a app real com
utilizadores simulados e relógio controlado (rotas). Nunca hardware, rede, LLM nem MCP.

Casa A é a demo (Ana, Bruno, Carla, Diogo, senhorio, operador; alvo SIMULADO: a tomada da
extensão) e casa B é de outra pessoa (Eva, inquilina; Hugo, senhorio). `add_house` cria casas
pequenas (2, 3 inquilinos…) para a votação por unanimidade.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.agent import TriggerKind
from homemind.contracts.common import stable_id
from homemind.core.access import get_clock
from homemind.core.db import Database, migrate
from homemind.features.auth.service import User, current_user
from homemind.features.automations.service import AutomationProposeIn, AutomationTriggerIn
from homemind.features.households.repo import (
    insert_household,
    insert_membership,
    insert_resident,
    insert_room,
    seed_demo,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
HOUSE_B = stable_id("household", "casa-b")
EVA, HUGO = stable_id("resident", "eva"), stable_id("resident", "hugo")
DEMO_PLUG = fx.METER  # a tomada da extensão (SIMULADA) do `DemoDevices`
DEMO_PLUG_NAME = fx.meter().name
LAMP = fx.LAMP


def add_house(conn, key: str, tenants: int, *, source=hh.SourceKind.demo):
    """Casa `key` com `tenants` inquilinos e um senhorio; devolve (casa, [inquilinos], senhorio)."""
    house = stable_id("household", key)
    insert_household(
        conn,
        hh.Household(
            id=house, name=f"Casa {key}",
            settings=hh.HouseholdSettings(source_kind=source), created_at=fx.T0,
        ),
    )  # fmt: skip
    people, landlord = [], stable_id("resident", key, "senhorio")
    insert_resident(conn, hh.Resident(id=landlord, display_name="Senhorio", auth_subject=None))
    insert_membership(
        conn,
        hh.Membership(
            id=stable_id("membership", key, "l"), household_id=house, resident_id=landlord,
            role=hh.MembershipRole.landlord, starts_on=date(2026, 9, 1),
            status=hh.MembershipStatus.active,
        ),
    )  # fmt: skip
    for i in range(tenants):
        rid, room = stable_id("resident", key, str(i)), stable_id("room", key, str(i))
        insert_room(
            conn, hh.Room(id=room, household_id=house, name=f"Q{i}", kind=hh.RoomKind.bedroom)
        )
        insert_resident(conn, hh.Resident(id=rid, display_name=f"R{i}", auth_subject=None))
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", key, str(i)), household_id=house, resident_id=rid,
                role=hh.MembershipRole.tenant, room_id=room, starts_on=date(2026, 9, 1),
                status=hh.MembershipStatus.active,
            ),
        )  # fmt: skip
        people.append(rid)
    return house, people, landlord


def seed_two_houses(conn) -> None:
    seed_demo(conn)
    insert_household(
        conn,
        hh.Household(
            id=HOUSE_B, name="Casa B",
            settings=hh.HouseholdSettings(source_kind=hh.SourceKind.demo), created_at=fx.T0,
        ),
    )  # fmt: skip
    room = stable_id("room", "b1")
    insert_room(
        conn, hh.Room(id=room, household_id=HOUSE_B, name="Quarto 1", kind=hh.RoomKind.bedroom)
    )
    for rid, name, sub in ((EVA, "Eva", "sub-eva"), (HUGO, "Hugo", "sub-hugo")):
        insert_resident(conn, hh.Resident(id=rid, display_name=name, auth_subject=sub))
    for rid, role, r in (
        (EVA, hh.MembershipRole.tenant, room),
        (HUGO, hh.MembershipRole.landlord, None),
    ):
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", "b", str(rid)), household_id=HOUSE_B, resident_id=rid,
                role=role, room_id=r, starts_on=date(2026, 9, 1),
                status=hh.MembershipStatus.active,
            ),
        )  # fmt: skip


def proposal(target=DEMO_PLUG, *, name="Desligar tomada em pico") -> AutomationProposeIn:
    return AutomationProposeIn(
        name=name,
        trigger=AutomationTriggerIn(
            kind=TriggerKind.power_above, device_id=target, threshold_w=1500, duration_s=1800
        ),
        target_device_id=target,
    )


def plugs() -> dict:
    """As tomadas conhecidas da casa (o que o router calcula com o diretório de dispositivos)."""
    return {DEMO_PLUG: DEMO_PLUG_NAME}


@pytest.fixture
def db():
    database = Database(":memory:")
    database.open()
    migrate(database)
    database.run_sync(seed_two_houses)
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
        real_app.state.db.run_sync(seed_two_houses)
        yield real_app
    real_app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def as_(sub: str) -> dict[str, str]:
    return {"x-test-sub": sub}
