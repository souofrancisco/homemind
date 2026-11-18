"""`notifications.automation_proposal` <- `automation.proposed` (SAFE-04): aviso da casa só aos
inquilinos, sem botões; o senhorio e o operador nunca o veem."""

from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.agent import AutomationStatus
from homemind.contracts.common import Origin, Provenance, ValueKind, replace
from homemind.contracts.notification import (
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    RefType,
)
from homemind.features.notifications.handlers import AUTOMATION_PROPOSAL_CONSUMER
from homemind.features.notifications.tests._bus import (
    NOW,
    all_notifications,
    created_events,
    deliver,
    visible_to,
)
from homemind.features.notifications.tests.conftest import seed_two_houses

REAL = Provenance(origin=Origin.real, kind=ValueKind.measured)
SIM = Provenance(origin=Origin.simulated, kind=ValueKind.measured)


@pytest.fixture
def seeded(db):
    db.run_sync(seed_two_houses)
    return db


def _event(status=AutomationStatus.proposed, provenance=SIM):
    rule = replace(fx.automation(), status=status)
    return de.AutomationProposed(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=provenance, data=rule
    )


def _go(db, *events, **kw):
    return deliver(db, AUTOMATION_PROPOSAL_CONSUMER, *events, **kw)


def test_cria_aviso_da_casa_sem_botoes_com_o_ref_da_regra(seeded):
    ev = _event()
    assert _go(seeded, ev) == [True]
    (n,) = all_notifications(seeded)
    assert n.kind is NotificationKind.automation_proposal
    assert n.scope is NotificationScope.household and n.recipient_resident_id is None
    assert n.severity is NotificationSeverity.info
    assert n.actions == [] and n.responder_ids == []
    assert (n.ref.type, n.ref.id) == (RefType.automation, ev.data.id)
    assert n.expires_at == NOW + timedelta(hours=24)
    assert ev.data.name in n.body and "maioria" in n.body and "nada é executado" in n.body
    assert "SIMULADO" in n.body
    assert len(created_events(seeded)) == 1


def test_origem_real_nao_diz_simulado(seeded):
    _go(seeded, _event(provenance=REAL))
    (n,) = all_notifications(seeded)
    assert n.origin is Origin.real and "SIMULADO" not in n.body


def test_reentrega_do_mesmo_evento_nao_duplica(seeded):
    assert _go(seeded, _event(), twice=True) == [True, False]
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


def test_regra_que_ja_nao_esta_por_votar_e_ignorada(seeded):
    _go(seeded, _event(status=AutomationStatus.draft))
    assert all_notifications(seeded) == []


def test_so_os_inquilinos_veem_o_senhorio_e_o_operador_nunca(seeded):
    _go(seeded, _event())
    for tenant in (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO):
        assert len(visible_to(seeded, tenant)) == 1
    for other in (fx.LANDLORD, fx.OPERATOR):
        assert visible_to(seeded, other) == []
