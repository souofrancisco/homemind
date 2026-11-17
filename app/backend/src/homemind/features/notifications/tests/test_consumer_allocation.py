"""`notifications.allocation_published` <- `billing.allocation_published`: «o teu recibo»."""

import re

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.notification import NotificationKind, NotificationScope, RefType
from homemind.features.notifications.handlers import ALLOCATION_CONSUMER
from homemind.features.notifications.tests._bus import (
    all_notifications,
    created_events,
    deliver,
    end_membership,
    visible_to,
)
from homemind.features.notifications.tests.conftest import seed_two_houses

REAL = Provenance(origin=Origin.real, kind=ValueKind.measured)


@pytest.fixture
def seeded(db):
    db.run_sync(seed_two_houses)
    return db


def _event(resident=fx.ANA, allocation="a1", *, provenance=fx.SIM_MEASURED, **kw):
    return de.BillingAllocationPublished(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=provenance,
        data=de.AllocationPublished(
            bill_id=fx.BILL_A, allocation_id=stable_id("allocation", allocation),
            resident_id=resident,
        ), **kw,
    )  # fmt: skip


def _go(db, *events, **kw):
    return deliver(db, ALLOCATION_CONSUMER, *events, **kw)


def test_cria_info_pessoal_ao_inquilino(seeded):
    assert _go(seeded, _event()) == [True]
    (n,) = all_notifications(seeded)
    assert n.kind is NotificationKind.info and n.scope is NotificationScope.personal
    assert n.recipient_resident_id == fx.ANA and n.actions == []
    assert (n.ref.type, n.ref.id) == (RefType.allocation, stable_id("allocation", "a1"))
    assert n.title == "Recibo disponível" and "(SIMULADO)" in n.body
    text = n.title + n.body
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text) and "Ana" not in text
    assert "€" not in text  # o valor é da app, não da notificação
    (created,) = created_events(seeded)
    assert created.event.data.recipient_resident_id == fx.ANA


def test_so_o_destinatario_ve_e_o_senhorio_nao_ve_o_dos_outros(seeded):
    _go(seeded, _event(fx.ANA), _event(fx.BRUNO, "a2"))
    assert len(visible_to(seeded, fx.ANA)) == 1
    assert len(visible_to(seeded, fx.BRUNO)) == 1
    assert visible_to(seeded, fx.CARLA) == []
    assert visible_to(seeded, fx.LANDLORD) == []  # `info` visível, mas é pessoal de outrem


def test_reentrega_e_republicacao_nao_duplicam(seeded):
    assert _go(seeded, _event(), twice=True) == [True, False]
    _go(seeded, _event())  # outro evento, mesma alocação
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


def test_membership_terminada_nao_recebe_nada(seeded):
    end_membership(seeded, fx.ANA)
    _go(seeded, _event())
    assert all_notifications(seeded) == []


@pytest.mark.parametrize("who", [fx.LANDLORD, fx.OPERATOR])
def test_so_inquilinos_ativos(seeded, who):
    _go(seeded, _event(who))
    assert all_notifications(seeded) == []


def test_origem_real_nao_diz_simulado(seeded):
    _go(seeded, _event(provenance=REAL))
    (n,) = all_notifications(seeded)
    assert n.origin is Origin.real and "SIMULADO" not in n.body
