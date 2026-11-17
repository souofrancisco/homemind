"""Varrimento de expiração: a função é testada diretamente; o laço com um intervalo mínimo."""

import asyncio
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.notification import NotificationKind, NotificationStatus
from homemind.features.notifications.handlers import (
    CONFIRMATION_CONSUMER,
    PRESENCE_CHECK_CONSUMER,
)
from homemind.features.notifications.sweeper import expiry_loop, sweep_once
from homemind.features.notifications.tests._bus import NOW, all_notifications, deliver
from homemind.features.notifications.tests.conftest import seed_two_houses


@pytest.fixture
def seeded(db):
    """Um pedido de confirmação (expira T0+24 h) e um «estás em casa?» (expira T0+30 min)."""
    db.run_sync(seed_two_houses)
    deliver(
        db,
        CONFIRMATION_CONSUMER,
        de.BillingConfirmationNeeded(
            ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=fx.SIM_INFERRED,
            data=fx.confirmation_request(),
        ),
    )  # fmt: skip
    deliver(
        db,
        PRESENCE_CHECK_CONSUMER,
        de.PresenceConfirmationNeeded(
            ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=fx.SIM_INFERRED,
            data=fx.presence_confirmation(),
        ),
    )  # fmt: skip
    return db


def _status(db):
    return {n.kind: n.status for n in all_notifications(db)}


def test_antes_do_prazo_nada_expira(seeded):
    assert seeded.run_sync(lambda c: sweep_once(c, lambda: NOW)) == 0
    assert set(_status(seeded).values()) == {NotificationStatus.unread}


def test_expira_so_as_vencidas_e_e_idempotente(seeded):
    later = fx.T0 + timedelta(hours=1)  # passou o «estás em casa?», não o pedido de 24 h
    assert seeded.run_sync(lambda c: sweep_once(c, lambda: later)) == 1
    assert _status(seeded) == {
        NotificationKind.presence_check: NotificationStatus.expired,
        NotificationKind.confirmation_request: NotificationStatus.unread,
    }
    assert seeded.run_sync(lambda c: sweep_once(c, lambda: later)) == 0
    end = fx.T0 + timedelta(hours=25)
    assert seeded.run_sync(lambda c: sweep_once(c, lambda: end)) == 1
    assert set(_status(seeded).values()) == {NotificationStatus.expired}


def test_laco_expira_e_cancela_sem_deixar_tarefas(seeded):
    clock = {"now": NOW}

    async def go():
        task = asyncio.create_task(expiry_loop(seeded, lambda: clock["now"], 0.01))
        clock["now"] = fx.T0 + timedelta(hours=1)
        for _ in range(100):
            await asyncio.sleep(0.02)
            if _status(seeded)[NotificationKind.presence_check] is NotificationStatus.expired:
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return task.cancelled()

    assert asyncio.run(go()) is True
    assert _status(seeded)[NotificationKind.presence_check] is NotificationStatus.expired


def test_laco_sobrevive_a_uma_falha(seeded, caplog):
    calls = []

    def flaky_clock():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("relógio avariado: segredo")
        return fx.T0 + timedelta(hours=1)

    async def go():
        task = asyncio.create_task(expiry_loop(seeded, flaky_clock, 0.01))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if _status(seeded)[NotificationKind.presence_check] is NotificationStatus.expired:
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    with caplog.at_level("WARNING"):
        asyncio.run(go())
    assert _status(seeded)[NotificationKind.presence_check] is NotificationStatus.expired
    assert "RuntimeError" in caplog.text and "segredo" not in caplog.text
