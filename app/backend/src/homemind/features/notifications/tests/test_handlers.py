"""O consumidor de `billing.confirmation_needed` sobre o barramento real e SQLite em memória."""

import asyncio
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Provenance, ValueKind, new_id
from homemind.contracts.notification import NotificationScope
from homemind.core.events import EventBus, load_events
from homemind.features.notifications.handlers import (
    CONFIRMATION_CONSUMER,
    CONFIRMATION_EVENT_TYPES,
    make_confirmation_handler,
)
from homemind.features.notifications.sqlite import SqliteNotificationRepository
from homemind.features.notifications.tests.conftest import seed_two_houses

NOW = fx.T0 + timedelta(minutes=5)
REAL = Provenance(origin="real", kind=ValueKind.inferred)


@pytest.fixture
def seeded(db):
    db.run_sync(seed_two_houses)
    return db


def _event(*, eligible=None, consumption=None, provenance=fx.SIM_INFERRED, expires_in=None):
    req = fx.confirmation_request()
    update = {}
    if eligible is not None:
        update["eligible_resident_ids"] = eligible
    if consumption is not None:
        update["consumption_event_id"] = consumption
    if expires_in is not None:
        update["expires_at"] = NOW + expires_in
    req = type(req).model_validate(req.model_dump() | update)
    return de.BillingConfirmationNeeded(
        ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=provenance, data=req
    )


def _deliver(db, *events, twice=False):
    """Publica e entrega cada evento ao consumidor; devolve os resultados de `deliver`."""
    bus = EventBus(db)
    bus.subscribe(
        CONFIRMATION_CONSUMER, make_confirmation_handler(lambda: NOW), CONFIRMATION_EVENT_TYPES
    )

    async def go():
        results = []
        for ev in events:
            stored = await bus.publish(ev)
            results.append(await bus.deliver(CONFIRMATION_CONSUMER, stored))
            if twice:
                results.append(await bus.deliver(CONFIRMATION_CONSUMER, stored))
        return results

    return asyncio.run(go())


def _notifications(db):
    return db.run_sync(lambda c: SqliteNotificationRepository(c).list_household(fx.HOUSEHOLD))


def _created(db):
    return db.run_sync(lambda c: load_events(c, types=["notification.created"]))


def test_o_mesmo_evento_duas_vezes_da_uma_notificacao_e_um_evento(seeded):
    assert _deliver(seeded, _event(), twice=True) == [True, False]
    (n,) = _notifications(seeded)
    (created,) = _created(seeded)
    assert created.event.data.notification_id == n.id
    assert created.event.household_id == fx.HOUSEHOLD


def test_republicar_o_mesmo_evento_nao_duplica(seeded):
    ev = _event()
    assert _deliver(seeded, ev, ev) == [True, False]
    assert len(_notifications(seeded)) == 1
    assert len(_created(seeded)) == 1


def test_outro_evento_para_o_mesmo_consumo_nao_cria_segundo_pedido_aberto(seeded):
    assert _deliver(seeded, _event(), _event()) == [True, True]  # eventos com ids diferentes
    assert len(_notifications(seeded)) == 1
    assert len(_created(seeded)) == 1


def test_senhorio_e_filtrado_dos_responsaveis(seeded):
    _deliver(seeded, _event(eligible=[fx.LANDLORD, fx.ANA, fx.BRUNO]))
    (n,) = _notifications(seeded)
    assert n.scope is NotificationScope.household
    assert n.responder_ids == [fx.ANA, fx.BRUNO]
    assert fx.LANDLORD not in n.responder_ids


def test_so_o_senhorio_elegivel_nao_cria_nada(seeded):
    assert _deliver(seeded, _event(eligible=[fx.LANDLORD])) == [True]  # processado, sem efeito
    assert _notifications(seeded) == []
    assert _created(seeded) == []


def test_pedido_expirado_e_um_no_op(seeded):
    _deliver(seeded, _event(expires_in=timedelta(seconds=-1)))
    assert _notifications(seeded) == []
    assert _created(seeded) == []


def test_origem_simulada_marca_simulado(seeded):
    _deliver(seeded, _event(provenance=fx.SIM_INFERRED))
    (n,) = _notifications(seeded)
    assert n.origin.value == "simulated"
    assert "(SIMULADO)" in n.body
    (created,) = _created(seeded)
    assert created.event.provenance == fx.SIM_INFERRED


def test_origem_real_nao_marca_simulado(seeded):
    _deliver(seeded, _event(provenance=REAL))
    (n,) = _notifications(seeded)
    assert n.origin.value == "real"
    assert "SIMULADO" not in n.body


def test_evento_de_outra_casa_nao_toca_na_casa_demo(seeded):
    from homemind.features.notifications.tests.conftest import EVA, HOUSE_B

    req = fx.confirmation_request()
    req = type(req).model_validate(req.model_dump() | {"eligible_resident_ids": [EVA]})
    ev = de.BillingConfirmationNeeded(
        id=new_id(), ts=fx.T0, household_id=HOUSE_B, provenance=fx.SIM_INFERRED, data=req
    )
    _deliver(seeded, ev)
    assert _notifications(seeded) == []
    other = seeded.run_sync(lambda c: SqliteNotificationRepository(c).list_household(HOUSE_B))
    assert len(other) == 1 and other[0].responder_ids == [EVA]
