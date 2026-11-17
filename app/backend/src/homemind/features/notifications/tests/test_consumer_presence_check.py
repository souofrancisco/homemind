"""`notifications.presence_check` <- `presence.confirmation_needed`: «estás em casa?» pessoal."""

import re
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.notification import (
    NotificationKind,
    NotificationScope,
    RefType,
)
from homemind.contracts.presence import (
    PRESENCE_CONFIRMATION_ACTIONS,
    PresenceConfirmationRequest,
    UncertainReason,
)
from homemind.features.notifications.handlers import PRESENCE_CHECK_CONSUMER
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


def _event(*, req=None, provenance=fx.SIM_INFERRED, **kw):
    return de.PresenceConfirmationNeeded(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=provenance,
        data=req or fx.presence_confirmation(), **kw,
    )  # fmt: skip


def _go(db, *events, **kw):
    return deliver(db, PRESENCE_CHECK_CONSUMER, *events, **kw)


def test_cria_pergunta_pessoal_com_as_acoes_do_contrato(seeded):
    assert _go(seeded, _event()) == [True]
    (n,) = all_notifications(seeded)
    req = fx.presence_confirmation()
    assert n.kind is NotificationKind.presence_check
    assert n.scope is NotificationScope.personal
    assert n.recipient_resident_id == fx.CARLA == req.resident_id
    assert n.responder_ids == [fx.CARLA]
    assert [a.id for a in n.actions] == list(PRESENCE_CONFIRMATION_ACTIONS) == ["in", "out"]
    assert [a.label for a in n.actions] == ["Estou em casa", "Estou fora"]
    assert n.expires_at == req.expires_at
    assert (n.ref.type, n.ref.id) == (RefType.presence_check, req.id)
    assert n.origin is Origin.simulated and "(SIMULADO)" in n.body
    (created,) = created_events(seeded)
    assert created.event.data.notification_id == n.id
    assert created.event.data.recipient_resident_id == fx.CARLA
    assert created.event.provenance == fx.SIM_INFERRED


def test_origem_real_nao_marca_simulado(seeded):
    _go(seeded, _event(provenance=REAL))
    (n,) = all_notifications(seeded)
    assert n.origin is Origin.real and "SIMULADO" not in n.body


def test_so_a_propria_pessoa_ve_e_o_senhorio_nunca(seeded):
    _go(seeded, _event())
    assert [v.kind for v in visible_to(seeded, fx.CARLA)] == [NotificationKind.presence_check]
    for other in (fx.ANA, fx.BRUNO, fx.DIOGO, fx.LANDLORD, fx.OPERATOR):
        assert visible_to(seeded, other) == []


def test_reentrega_do_mesmo_evento_e_idempotente(seeded):
    assert _go(seeded, _event(), twice=True) == [True, False]
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


def test_outro_evento_para_o_mesmo_pedido_nao_duplica(seeded):
    assert _go(seeded, _event(), _event()) == [True, True]  # ids de evento diferentes
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


def test_pedidos_diferentes_dao_perguntas_diferentes(seeded):
    other = fx.presence_confirmation().model_copy(
        update={"id": fx.stable_id("presence-check", "2")}
    )
    _go(seeded, _event(), _event(req=other))
    assert len(all_notifications(seeded)) == 2


def test_membership_terminada_nao_recebe_nada(seeded):
    end_membership(seeded, fx.CARLA)
    assert _go(seeded, _event()) == [True]  # processado, sem efeito
    assert all_notifications(seeded) == []
    assert created_events(seeded) == []


@pytest.mark.parametrize("who", [fx.LANDLORD, fx.OPERATOR])
def test_so_inquilinos_ativos(seeded, who):
    req = fx.presence_confirmation().model_copy(update={"resident_id": who})
    _go(seeded, _event(req=req))
    assert all_notifications(seeded) == []


def test_nao_membro_da_casa_nao_recebe_nada(seeded):
    from homemind.features.notifications.tests.conftest import EVA

    req = fx.presence_confirmation().model_copy(update={"resident_id": EVA})  # Eva é da casa B
    _go(seeded, _event(req=req))
    assert all_notifications(seeded) == []


def test_pedido_ja_expirado_e_saltado(seeded):
    late = NOW + timedelta(hours=2)
    _go(seeded, _event(), now=late)
    assert all_notifications(seeded) == []
    assert created_events(seeded) == []


@pytest.mark.parametrize("reason", list(UncertainReason))
def test_texto_e_sempre_uma_pergunta_sem_privacidade_violada(seeded, reason):
    req = PresenceConfirmationRequest(
        id=fx.stable_id("presence-check", str(reason)),
        resident_id=fx.CARLA,
        reason=reason,
        expires_at=fx.T0 + timedelta(minutes=30),
    )
    _go(seeded, _event(req=req))
    (n,) = all_notifications(seeded)
    text = f"{n.title} {n.body}"
    assert n.title.endswith("?") and "?" in n.body
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text)  # sem UUIDs
    assert not re.search(r"\d", text.replace("(SIMULADO)", ""))  # sem horas nem números
    for forbidden in ("Carla", "Wi-Fi", "wifi", "aparelho", "câmara", "porta", "telemóvel"):
        assert forbidden.lower() not in text.lower()
    for accusation in ("mentir", "suspeit", "não estás", "ausente"):
        assert accusation not in text.lower()
