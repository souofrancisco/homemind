from datetime import UTC, date, datetime

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.common import stable_id
from homemind.contracts.household import MembershipRole
from homemind.features.households.repo import insert_membership, insert_resident, insert_room
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.tests.conftest import (
    EVA,
    FRED,
    HOUSE_B,
    M_EVA,
    seed_two_houses,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
GIL = stable_id("resident", "gil")


@pytest.fixture
def seeded(db):
    db.run_sync(seed_two_houses)
    return db


def role(db, house, resident, at=NOW):
    return db.run_sync(lambda c: SqliteResidentDirectory(c).role_in(house, resident, at))


def test_papeis_ativos(seeded):
    assert role(seeded, fx.HOUSEHOLD, fx.ANA) is MembershipRole.tenant
    assert role(seeded, fx.HOUSEHOLD, fx.LANDLORD) is MembershipRole.landlord
    assert role(seeded, fx.HOUSEHOLD, fx.OPERATOR) is MembershipRole.operator


def test_nao_membro_e_casa_inexistente(seeded):
    assert role(seeded, HOUSE_B, fx.ANA) is None  # Ana não é da casa B
    assert role(seeded, fx.HOUSEHOLD, stable_id("resident", "ninguem")) is None
    assert role(seeded, stable_id("household", "nao-existe"), fx.ANA) is None


def test_membership_terminada_nao_conta(seeded):
    assert role(seeded, HOUSE_B, FRED) is None  # `ended` com `ends_on` passado


def test_membership_futura_nao_conta_ainda(seeded):
    def future(conn):
        insert_resident(conn, hh.Resident(id=GIL, display_name="Gil"))
        room = stable_id("room", "b3")
        insert_room(
            conn,
            hh.Room(id=room, household_id=HOUSE_B, name="Quarto 3", kind=hh.RoomKind.bedroom),
        )
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", "gil"),
                household_id=HOUSE_B,
                resident_id=GIL,
                role=MembershipRole.tenant,
                room_id=room,
                starts_on=date(2026, 12, 1),
                status=hh.MembershipStatus.active,
            ),
        )

    seeded.run_sync(future)
    assert role(seeded, HOUSE_B, GIL, NOW) is None
    first_day = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    assert role(seeded, HOUSE_B, GIL, first_day) is MembershipRole.tenant


def test_fim_inclusivo_e_dia_no_fuso_da_casa(seeded):
    # Eva está `active` com `ends_on` = 17/11 (o estado ainda não foi atualizado).
    seeded.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET ends_on = '2026-11-17' WHERE id = ?", (str(M_EVA),)
        )
    )
    assert role(seeded, HOUSE_B, EVA, NOW) is MembershipRole.tenant  # `ends_on` é inclusivo
    late = datetime(2026, 11, 17, 23, 30, tzinfo=UTC)
    assert role(seeded, HOUSE_B, EVA, late) is MembershipRole.tenant  # Lisboa = UTC no inverno
    assert role(seeded, HOUSE_B, EVA, datetime(2026, 11, 18, 0, 30, tzinfo=UTC)) is None
    # Num fuso a +13 h, 12:00 UTC de 17/11 já é 18/11: «hoje» conta no fuso da casa.
    seeded.run_sync(
        lambda c: c.execute(
            "UPDATE household SET timezone = 'Pacific/Auckland' WHERE id = ?", (str(HOUSE_B),)
        )
    )
    assert role(seeded, HOUSE_B, EVA, NOW) is None
    assert role(seeded, HOUSE_B, EVA, datetime(2026, 11, 17, 6, 0, tzinfo=UTC)) is (
        MembershipRole.tenant
    )
