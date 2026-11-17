from datetime import time

import pytest

from homemind.contracts.notification import (
    NotificationKind,
    NotificationPreferences,
    NotificationSeverity,
    QuietHours,
)
from homemind.features.notifications.preferences import Delivery, delivery_for, in_quiet_hours
from homemind.features.notifications.tests._fakes import ANA

NIGHT = QuietHours(start=time(22, 0), end=time(8, 0))
DAY = QuietHours(start=time(13, 0), end=time(15, 0))


@pytest.mark.parametrize(
    ("qh", "t", "expected"),
    [
        (NIGHT, time(23, 0), True),
        (NIGHT, time(22, 0), True),
        (NIGHT, time(0, 0), True),
        (NIGHT, time(7, 59), True),
        (NIGHT, time(8, 0), False),
        (NIGHT, time(12, 0), False),
        (NIGHT, time(21, 59), False),
        (DAY, time(13, 0), True),
        (DAY, time(14, 59), True),
        (DAY, time(15, 0), False),
        (DAY, time(12, 59), False),
        (QuietHours(start=time(9, 0), end=time(9, 0)), time(9, 0), False),
    ],
)
def test_in_quiet_hours(qh, t, expected):
    assert in_quiet_hours(qh, t) is expected


def _prefs(**kw):
    return NotificationPreferences(resident_id=ANA, **kw)


def _d(kind, prefs, t, severity=NotificationSeverity.info):
    return delivery_for(kind, severity, prefs, t)


def test_sem_preferencias_entrega_agora():
    assert _d(NotificationKind.budget_alert, None, time(3, 0)) is Delivery.now


def test_tipo_desativado_e_suprimido():
    prefs = _prefs(disabled_kinds=[NotificationKind.saving_tip])
    assert _d(NotificationKind.saving_tip, prefs, time(12, 0)) is Delivery.suppressed
    assert _d(NotificationKind.budget_alert, prefs, time(12, 0)) is Delivery.now


def test_horas_de_silencio_adiam():
    prefs = _prefs(quiet_hours=NIGHT)
    assert _d(NotificationKind.budget_alert, prefs, time(23, 30)) is Delivery.deferred
    assert _d(NotificationKind.budget_alert, prefs, time(12, 0)) is Delivery.now


def test_seguranca_ignora_silencio_e_qualquer_severidade():
    prefs = _prefs(quiet_hours=NIGHT)
    for sev in NotificationSeverity:
        assert _d(NotificationKind.security_alert, prefs, time(23, 30), sev) is Delivery.now


def test_suprimido_tem_prioridade_sobre_adiado():
    prefs = _prefs(quiet_hours=NIGHT, disabled_kinds=[NotificationKind.peak_alert])
    assert _d(NotificationKind.peak_alert, prefs, time(23, 30)) is Delivery.suppressed
