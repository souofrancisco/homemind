"""`notifications.attribution_changed` <- `billing.attribution_changed`: informação pessoal sobre
um «De quem é esta conta?» que a P3 perguntou."""

import re
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import (
    Attribution,
    AttributionMethod,
    AttributionStatus,
    AttributionTarget,
)
from homemind.contracts.common import Audit, Origin, Provenance, ValueKind, replace, stable_id
from homemind.contracts.notification import NotificationKind, NotificationScope, RefType
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.handlers import ATTRIBUTION_CONSUMER, CONFIRMATION_CONSUMER
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository
from homemind.features.notifications.tests._bus import (
    NOW,
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
    """Casa demo com o pedido «De quem é esta conta?» do consumo das fixtures já criado."""
    db.run_sync(seed_two_houses)
    ev = de.BillingConfirmationNeeded(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=fx.SIM_INFERRED,
        data=fx.confirmation_request(),
    )  # fmt: skip
    deliver(db, CONFIRMATION_CONSUMER, ev)
    return db


def _vote(db, resident, action, target=None):
    def work(c):
        repo = SqliteNotificationRepository(c)
        svc = NotificationService(repo, SqliteResidentDirectory(c), lambda: NOW)
        (n,) = [x for x in repo.list_household(fx.HOUSEHOLD)
                if x.kind is NotificationKind.confirmation_request]  # fmt: skip
        svc.respond(
            n.id, household_id=fx.HOUSEHOLD, resident_id=resident, action_id=action,
            target_resident_id=target,
        )  # fmt: skip

    db.run_sync(work)


def _attribution(**kw) -> Attribution:
    return replace(fx.carla_attribution(), **kw)


def _common(**kw) -> Attribution:
    base = {
        "id": stable_id("attribution", "comum"),
        "target_type": AttributionTarget.common,
        "target_resident_id": None,
        "method": AttributionMethod.equal_fallback,
        "decided_by": Audit(at=fx.T0 + timedelta(hours=24), by_system="billing"),
    }
    return replace(fx.carla_attribution(), **(base | kw))


def _event(a: Attribution, **kw) -> de.BillingAttributionChanged:
    return de.BillingAttributionChanged(
        ts=fx.T0, household_id=a.household_id, provenance=a.provenance, data=a, **kw
    )


def _go(db, *events, **kw):
    return deliver(db, ATTRIBUTION_CONSUMER, *events, **kw)


def _infos(db):
    return [n for n in all_notifications(db) if n.kind is NotificationKind.info]


def _clean(text: str) -> None:
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text)  # sem UUIDs
    for name in ("Ana", "Bruno", "Carla", "Diogo", "Aquecedor", "aquecedor", "Sr. Silva"):
        assert name not in text  # nem nomes de terceiros nem de aparelhos (P-18)


def test_pagador_recebe_registado_na_tua_conta(seeded):
    _vote(seeded, fx.CARLA, "mine")
    assert _go(seeded, _event(fx.carla_attribution())) == [True]
    (n,) = _infos(seeded)
    assert n.scope is NotificationScope.personal and n.recipient_resident_id == fx.CARLA
    assert n.title == "Registado na tua conta" and "(SIMULADO)" in n.body
    assert n.actions == [] and n.responder_ids == []
    assert (n.ref.type, n.ref.id) == (RefType.consumption_event, fx.CONSUMPTION)
    _clean(n.title + n.body)
    assert {v.kind for v in visible_to(seeded, fx.CARLA)} == {
        NotificationKind.confirmation_request,
        NotificationKind.info,
    }
    (created,) = [e for e in created_events(seeded) if e.event.data.kind is NotificationKind.info]
    assert created.event.data.recipient_resident_id == fx.CARLA


def test_atribuido_por_votacao_a_outro_o_pagador_nao_precisa_de_ter_votado(seeded):
    for voter in (fx.ANA, fx.BRUNO):
        _vote(seeded, voter, "other", fx.CARLA)
    _go(seeded, _event(fx.carla_attribution()))
    (n,) = _infos(seeded)
    assert n.recipient_resident_id == fx.CARLA
    _clean(n.title + n.body)  # não diz quem votou nem quem acusou
    assert visible_to(seeded, fx.ANA)[0].kind is NotificationKind.confirmation_request
    assert all(v.kind is not NotificationKind.info for v in visible_to(seeded, fx.ANA))


def test_comum_vai_a_cada_votante_e_so_a_eles(seeded):
    _vote(seeded, fx.ANA, "unknown")
    _vote(seeded, fx.BRUNO, "everyone")
    _go(seeded, _event(_common()))
    infos = _infos(seeded)
    assert {n.recipient_resident_id for n in infos} == {fx.ANA, fx.BRUNO}
    for n in infos:
        assert n.scope is NotificationScope.personal  # nunca da casa
        assert n.title == "Dividido por todos"
        _clean(n.title + n.body)
    assert all(v.kind is not NotificationKind.info for v in visible_to(seeded, fx.DIOGO))
    assert visible_to(seeded, fx.LANDLORD) == []
    assert (
        len([e for e in created_events(seeded) if e.event.data.kind is NotificationKind.info]) == 2
    )


def test_comum_sem_votantes_nao_notifica_ninguem(seeded):
    _go(seeded, _event(_common()))
    assert _infos(seeded) == []


def test_comum_ignora_votante_que_ja_saiu(seeded):
    _vote(seeded, fx.ANA, "unknown")
    _vote(seeded, fx.BRUNO, "everyone")
    end_membership(seeded, fx.BRUNO)
    _go(seeded, _event(_common()))
    assert [n.recipient_resident_id for n in _infos(seeded)] == [fx.ANA]


def test_atribuicao_de_consumo_que_a_p3_nao_perguntou_e_ignorada(seeded):
    other = _attribution(consumption_event_id=stable_id("consumption", "outro"))
    assert _go(seeded, _event(other)) == [True]
    assert _infos(seeded) == []
    assert created_events(seeded)  # só o do pedido original


def test_atribuicao_substituida_e_ignorada(seeded):
    _vote(seeded, fx.CARLA, "mine")
    old = _attribution(status=AttributionStatus.superseded)
    _go(seeded, _event(old))
    assert _infos(seeded) == []


def test_pagador_que_saiu_da_casa_nao_recebe_nada(seeded):
    _vote(seeded, fx.CARLA, "mine")
    end_membership(seeded, fx.CARLA)
    _go(seeded, _event(fx.carla_attribution()))
    assert _infos(seeded) == []


def test_reentrega_e_idempotente(seeded):
    _vote(seeded, fx.CARLA, "mine")
    assert _go(seeded, _event(fx.carla_attribution()), twice=True) == [True, False]
    assert len(_infos(seeded)) == 1


def test_mesma_atribuicao_com_outro_evento_nao_duplica(seeded):
    _vote(seeded, fx.CARLA, "mine")
    a = fx.carla_attribution()
    _go(seeded, _event(a), _event(a))
    assert len(_infos(seeded)) == 1


def test_nova_atribuicao_do_mesmo_consumo_avisa_de_novo(seeded):
    _vote(seeded, fx.CARLA, "mine")
    first = fx.carla_attribution()
    second = _attribution(id=stable_id("attribution", "2"), supersedes_id=first.id)
    _go(seeded, _event(first), _event(second))
    assert len(_infos(seeded)) == 2


def test_origem_real_nao_diz_simulado(seeded):
    _vote(seeded, fx.CARLA, "mine")
    _go(seeded, _event(_attribution(provenance=REAL)))
    (n,) = _infos(seeded)
    assert n.origin is Origin.real and "SIMULADO" not in n.body
