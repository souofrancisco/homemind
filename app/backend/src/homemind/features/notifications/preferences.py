"""Preferências de entrega: tipos desligados e horas de silêncio.

Só afetam o push; a notificação persiste-se sempre e aparece no centro de notificações.
"""

from datetime import time
from enum import StrEnum

from homemind.contracts.notification import (
    NotificationKind,
    NotificationPreferences,
    NotificationSeverity,
    QuietHours,
)


class Delivery(StrEnum):
    now = "now"  # entregar já (push)
    deferred = "deferred"  # horas de silêncio: entregar depois
    suppressed = "suppressed"  # tipo desligado: sem push


def in_quiet_hours(qh: QuietHours, t: time) -> bool:
    """`t` está na janela [start, end)? Suporta janelas que atravessam a meia-noite.

    `start == end` é uma janela vazia (nunca silencia).
    """
    if qh.start <= qh.end:
        return qh.start <= t < qh.end
    return t >= qh.start or t < qh.end


def delivery_for(
    kind: NotificationKind,
    severity: NotificationSeverity,
    prefs: NotificationPreferences | None,
    local_time: time,
) -> Delivery:
    """Como entregar o push. `security_alert` é sempre imediato, qualquer que seja a severidade.

    `severity` fica na assinatura para a regra do bypass das horas de silêncio, ainda por
    confirmar com a equipa (ver docs/modules/notifications.md).
    """
    if kind is NotificationKind.security_alert or prefs is None:
        return Delivery.now
    if kind in prefs.disabled_kinds:
        return Delivery.suppressed
    if prefs.quiet_hours is not None and in_quiet_hours(prefs.quiet_hours, local_time):
        return Delivery.deferred
    return Delivery.now
