"""`notifications.agent_action` <- `agent.action_proposed`: «Ação por confirmar», sem botões."""

from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, replace, stable_id
from homemind.contracts.notification import (
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    RefType,
)
from homemind.features.notifications.handlers import AGENT_ACTION_CONSUMER
from homemind.features.notifications.tests._bus import (
    NOW,
    all_notifications,
    created_events,
    deliver,
    end_membership,
    visible_to,
)
from homemind.features.notifications.tests.conftest import seed_two_houses

REAL = Provenance(origin=Origin.real, kind=ValueKind.inferred)


@pytest.fixture
def seeded(db):
    db.run_sync(seed_two_houses)
    return db


def _event(*, for_resident=fx.BRUNO, name="a1", provenance=fx.SIM_INFERRED, **changes):
    action = replace(
        fx.proposed_action(),
        id=stable_id("action", name),
        proposed_for_resident_id=for_resident,
        **changes,
    )
    return de.AgentActionProposed(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=provenance, data=action
    )


def _go(db, *events, **kw):
    return deliver(db, AGENT_ACTION_CONSUMER, *events, **kw)


def test_cria_notificacao_pessoal_sem_botoes_com_o_ref_da_acao(seeded):
    ev = _event()
    assert _go(seeded, ev) == [True]
    (n,) = all_notifications(seeded)
    assert n.kind is NotificationKind.agent_action and n.scope is NotificationScope.personal
    assert n.severity is NotificationSeverity.info and n.recipient_resident_id == fx.BRUNO
    assert n.actions == [] and n.responder_ids == []
    assert (n.ref.type, n.ref.id) == (RefType.agent_action, ev.data.id)
    assert n.expires_at == ev.data.expires_at
    assert n.title == "Ação por confirmar"
    assert ev.data.rationale in n.body and "Nada é executado sem a tua confirmação." in n.body
    assert "(SIMULADO)" in n.body
    (created,) = created_events(seeded)
    assert created.event.data.recipient_resident_id == fx.BRUNO


def test_origem_real_nao_diz_simulado(seeded):
    _go(seeded, _event(provenance=REAL))
    (n,) = all_notifications(seeded)
    assert n.origin is Origin.real and "SIMULADO" not in n.body


def test_reentrega_do_mesmo_evento_nao_duplica(seeded):
    assert _go(seeded, _event(), twice=True) == [True, False]
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


def test_proposta_ja_expirada_e_ignorada(seeded):
    _go(seeded, _event(proposed_at=NOW - timedelta(minutes=15), expires_at=NOW))
    assert all_notifications(seeded) == []


@pytest.mark.parametrize("who", [fx.LANDLORD, fx.OPERATOR])
def test_destinatario_que_nao_e_inquilino_nao_recebe(seeded, who):
    _go(seeded, _event(for_resident=who))
    assert all_notifications(seeded) == []


def test_inquilino_que_saiu_nao_recebe(seeded):
    end_membership(seeded, fx.BRUNO)
    _go(seeded, _event())
    assert all_notifications(seeded) == []


def test_so_o_destinatario_ve_e_o_senhorio_nunca(seeded):
    _go(seeded, _event())
    assert len(visible_to(seeded, fx.BRUNO)) == 1
    for other in (fx.ANA, fx.CARLA, fx.LANDLORD):
        assert visible_to(seeded, other) == []
    assert visible_to(seeded, fx.BRUNO, now=NOW + timedelta(minutes=1))[0].actions == []
