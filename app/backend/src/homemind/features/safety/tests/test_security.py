"""SAFE-02: painel de segurança SIMULADO (serviço sobre SQLite em memória, relógio simulado)."""

from datetime import timedelta
from uuid import UUID

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.safety import (
    AwayStatus,
    SecurityAction,
    SecurityActionKind,
    SecurityActionStatus,
    SecurityPanelState,
    SecurityPanelStatus,
)
from homemind.core.events import load_events
from homemind.features.safety import security as sec
from homemind.features.safety.tests.conftest import HOUSE_B, HOUSE_REAL, NOW

A = fx.HOUSEHOLD
RESIDENT = UUID(int=7)
ARM, DISARM = SecurityActionKind.arm, SecurityActionKind.disarm
AW, HOME, UNK = AwayStatus.away, AwayStatus.home, AwayStatus.unknown
P_ARM, P_DIS, P_UNK = (
    SecurityPanelStatus.armed,
    SecurityPanelStatus.disarmed,
    SecurityPanelStatus.unknown,
)


def run(db, fn, **kw):
    return db.run_sync(fn)


def get(db, away=UNK, now=NOW, house=A):
    return db.run_sync(lambda c: sec.get_view(c, house, away, now))


def propose(db, kind=ARM, away=UNK, now=NOW, house=A):
    return db.run_sync(lambda c: sec.propose(c, house, kind, away, now))


def decide(db, aid, confirm=True, away=UNK, now=NOW, house=A):
    return db.run_sync(lambda c: sec.decide(c, house, RESIDENT, aid, confirm, away, now))


# --- assess: o painel nunca decide AWAY ----------------------------------------------------


@pytest.mark.parametrize(
    "away,panel,expected",
    [
        (AW, P_ARM, sec.Assessment.consistent),
        (AW, P_DIS, sec.Assessment.suggest_arm),
        (HOME, P_ARM, sec.Assessment.armed_with_people),
        (HOME, P_DIS, sec.Assessment.normal),
        # sem sinal: nunca se infere casa vazia (nem armado/desarmado) de uma falha
        (UNK, P_ARM, sec.Assessment.no_signal),
        (UNK, P_DIS, sec.Assessment.no_signal),
        (UNK, P_UNK, sec.Assessment.no_signal),
        (AW, P_UNK, sec.Assessment.no_signal),
        (HOME, P_UNK, sec.Assessment.no_signal),
    ],
)
def test_assess_matrix(away, panel, expected):
    assert sec.assess(away, panel) is expected


def test_panel_armed_alone_never_makes_the_house_away():
    # o resultado depende do AWAY de entrada (vem da presença); o painel não o altera
    for panel in SecurityPanelStatus:
        assert sec.assess(UNK, panel) is sec.Assessment.no_signal


# --- vista ---------------------------------------------------------------------------------


def test_view_without_reading_is_unknown_and_simulated(db):
    v = get(db)
    assert v.available and v.origin == "simulated" and v.panel_status is P_UNK
    assert v.panel_since is None and v.pending is None
    assert v.assessment is sec.Assessment.no_signal
    assert v.can_arm and v.can_disarm  # sem leitura: ambas permitidas (só simulado)
    assert "SIMULADO" in v.notice and "nada é armado" in v.notice


def test_real_household_has_no_panel(db):
    v = get(db, house=HOUSE_REAL)
    assert not v.available and not v.can_arm and not v.can_disarm
    r = propose(db, house=HOUSE_REAL)
    assert r.error == sec.UNAVAILABLE and not r.events
    assert decide(db, UUID(int=1), house=HOUSE_REAL).error == sec.UNAVAILABLE


# --- proposta → confirmação ----------------------------------------------------------------


def test_propose_changes_nothing_until_confirmed(db):
    r = propose(db)
    assert r.error is None and [e.type for e in r.events] == ["safety.security_action"]
    v = r.view
    assert v.pending and v.pending.status is SecurityActionStatus.proposed
    assert v.pending.executed is False and v.panel_status is P_UNK
    assert v.pending.expires_at == NOW + sec.PROPOSAL_TTL
    assert not v.can_arm and not v.can_disarm  # há uma pendente
    types = [s.event.type for s in db.run_sync(lambda c: load_events(c))]
    assert "safety.security_changed" not in types


def test_confirm_arms_only_the_simulated_panel_and_labels_the_result(db):
    aid = propose(db).view.pending.id
    later = NOW + timedelta(minutes=2)
    r = decide(db, aid, now=later)
    assert r.error is None
    assert [e.type for e in r.events] == ["safety.security_action", "safety.security_changed"]
    v = r.view
    assert v.panel_status is P_ARM and v.panel_since == later and v.pending is None
    assert (
        v.last_result
        and v.last_result.startswith("SIMULADO")
        and "Nenhum alarme real" in v.last_result
    )
    assert not v.can_arm and v.can_disarm
    ev = r.events[0].data
    assert isinstance(ev, SecurityAction) and ev.status is SecurityActionStatus.confirmed
    assert ev.executed is False and ev.provenance.simulated and ev.decided_by == RESIDENT
    panel = r.events[1].data
    assert isinstance(panel, SecurityPanelState) and panel.provenance.simulated
    # a leitura seguinte (outra consulta) continua armada e sem `last_result`
    again = get(db, now=later)
    assert again.panel_status is P_ARM and again.last_result is None


def test_disarm_roundtrip(db):
    decide(db, propose(db).view.pending.id)
    aid = propose(db, DISARM).view.pending.id
    v = decide(db, aid).view
    assert v.panel_status is P_DIS and v.last_result.startswith("SIMULADO")
    assert v.can_arm and not v.can_disarm


def test_cancel_changes_nothing(db):
    aid = propose(db).view.pending.id
    r = decide(db, aid, confirm=False)
    assert [e.type for e in r.events] == ["safety.security_action"]
    assert r.events[0].data.status is SecurityActionStatus.cancelled
    assert r.view.panel_status is P_UNK and r.view.pending is None and r.view.last_result is None
    assert r.view.can_arm


def test_one_pending_proposal_at_a_time(db):
    propose(db)
    assert propose(db, DISARM).error == sec.PENDING_EXISTS


def test_confirm_twice_or_cancel_after_confirm_is_refused(db):
    aid = propose(db).view.pending.id
    assert decide(db, aid).error is None
    assert decide(db, aid).error == sec.NOT_PENDING
    assert decide(db, aid, confirm=False).error == sec.NOT_PENDING
    events = db.run_sync(lambda c: load_events(c, types=["safety.security_changed"]))
    assert len(events) == 1  # nunca duplica a mudança do painel


def test_expired_proposal_cannot_be_confirmed_and_frees_the_slot(db):
    aid = propose(db).view.pending.id
    late = NOW + sec.PROPOSAL_TTL
    assert decide(db, aid, now=late).error == sec.EXPIRED
    v = get(db, now=late)
    assert v.pending is None and v.panel_status is P_UNK and v.can_arm
    assert propose(db, now=late).error is None  # já se pode propor outra


def test_unknown_or_foreign_proposal_is_not_found(db):
    aid = propose(db).view.pending.id
    assert decide(db, UUID(int=999)).error == sec.NOT_FOUND
    assert decide(db, aid, house=HOUSE_B).error == sec.NOT_FOUND  # outra casa: nunca se vê


def test_not_applicable_when_already_in_that_state(db):
    decide(db, propose(db).view.pending.id)  # armado
    assert propose(db, ARM).error == sec.NOT_APPLICABLE
    decide(db, propose(db, DISARM).view.pending.id)  # desarmado
    assert propose(db, DISARM).error == sec.NOT_APPLICABLE


def test_panels_are_per_household(db):
    decide(db, propose(db).view.pending.id)
    assert get(db).panel_status is P_ARM
    assert get(db, house=HOUSE_B).panel_status is P_UNK


# --- contratos e privacidade ---------------------------------------------------------------


def test_view_has_no_personal_data(db):
    aid = propose(db).view.pending.id
    dumped = decide(db, aid).view.model_dump_json()
    assert str(RESIDENT) not in dumped and "decided_by" not in dumped
    pending = propose(db, DISARM).view.model_dump_json()
    assert "resident" not in pending and "decided_by" not in pending


def test_panel_accepts_real_provenance_but_actions_stay_simulated():
    real = fx.SIM_INFERRED.model_copy(update={"origin": "real"})
    # SAFE-02 leitura MCP: o estado do painel pode ser REAL (só leitura); as ações nunca
    assert (
        SecurityPanelState(
            id=UUID(int=1), household_id=A, status=P_ARM, since=NOW, provenance=real
        ).provenance.origin
        == "real"
    )
    with pytest.raises(ValueError):
        SecurityAction(
            id=UUID(int=1), household_id=A, kind=ARM, proposed_at=NOW,
            expires_at=NOW + timedelta(minutes=1), provenance=real,
        )  # fmt: skip
    with pytest.raises(ValueError):  # `executed` nunca pode ser verdadeiro
        SecurityAction(
            id=UUID(int=1), household_id=A, kind=ARM, proposed_at=NOW,
            expires_at=NOW + timedelta(minutes=1), provenance=fx.SIM_INFERRED, executed=True,
        )  # fmt: skip
    with pytest.raises(ValueError):  # decidida sem decisor
        SecurityAction(
            id=UUID(int=1), household_id=A, kind=ARM, status=SecurityActionStatus.confirmed,
            proposed_at=NOW, expires_at=NOW + timedelta(minutes=1), provenance=fx.SIM_INFERRED,
        )  # fmt: skip
