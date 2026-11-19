"""`notifications.automation_proposal` <- `automation.proposed` (SAFE-04): aviso da casa só aos
inquilinos, sem botões; o senhorio e o operador nunca o veem."""

from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.agent import AutomationStatus, RuleVerdict
from homemind.contracts.common import Origin, Provenance, ValueKind, replace, stable_id
from homemind.contracts.notification import (
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    NotificationStatus,
    RefType,
)
from homemind.features.notifications.handlers import (
    AUTOMATION_DECIDED_CONSUMER,
    AUTOMATION_PROPOSAL_CONSUMER,
)
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


def _event(status=AutomationStatus.proposed, provenance=SIM, name=None):
    rule = replace(fx.automation(), status=status, approved_by_resident_id=fx.ANA)
    extra = {"id": stable_id("automation.proposed", name)} if name else {}
    return de.AutomationProposed(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=provenance, data=rule, **extra
    )


def _decided(verdict=RuleVerdict.approved):
    return de.AutomationVoteDecided(
        ts=fx.T0,
        household_id=fx.HOUSEHOLD,
        provenance=SIM,
        data=de.AutomationVoteDecidedData(
            rule_id=fx.automation().id, verdict=verdict, votes_for=3, votes_against=0, eligible=4
        ),
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
    _go(seeded, _event(status=AutomationStatus.active))
    assert all_notifications(seeded) == []


def test_reativacao_avisa_uma_vez_por_ronda_com_o_texto_de_reativacao(seeded):
    first, again = _event(name="r1"), _event(status=AutomationStatus.disabled, name="r2")
    assert _go(seeded, first, again, twice=True) == [True, False, True, False]
    a, b = sorted(all_notifications(seeded), key=lambda n: "reativação" in n.body)
    assert "reativação" not in a.body and "reativação" in b.body
    assert a.id != b.id and a.ref == b.ref  # mesma regra, uma notificação por ronda
    assert len(created_events(seeded)) == 2


def test_a_votacao_decidida_fecha_o_aviso_e_e_idempotente(seeded):
    _go(seeded, _event())
    assert [n.status for n in all_notifications(seeded)] == [NotificationStatus.unread]
    for _ in range(2):
        deliver(seeded, AUTOMATION_DECIDED_CONSUMER, _decided(), twice=True)
        (n,) = all_notifications(seeded)
        assert n.status is NotificationStatus.expired
    assert visible_to(seeded, fx.LANDLORD) == []


def test_so_os_inquilinos_veem_o_senhorio_e_o_operador_nunca(seeded):
    _go(seeded, _event())
    for tenant in (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO):
        assert len(visible_to(seeded, tenant)) == 1
    for other in (fx.LANDLORD, fx.OPERATOR):
        assert visible_to(seeded, other) == []


def test_texto_do_gatilho_em_portugues_correto():
    from homemind.contracts.agent import AutomationTrigger, TriggerKind
    from homemind.features.notifications.compose import compose_automation_proposal

    base = fx.automation()
    power = replace(
        base,
        trigger=AutomationTrigger(
            kind=TriggerKind.power_above,
            device_id=base.actions[0].target_device_id,
            threshold_w=1500,
            duration_s=300,
        ),
    )
    presence = replace(base, trigger=AutomationTrigger(kind=TriggerKind.presence_changed))
    bodies = [
        compose_automation_proposal(
            rule=r,
            source_event_id=fx.automation().id,
            origin=Origin.real,
            correlation_id=fx.automation().id,
            now=NOW,
        ).body
        for r in (power, presence)
    ]
    assert "desligar uma tomada quando a potência passar de 1500 W durante 300 s." in bodies[0]
    assert "desligar uma tomada quando mudar quem está em casa." in bodies[1]
    assert not any(" ao a " in b or " ao mudar" in b for b in bodies)
