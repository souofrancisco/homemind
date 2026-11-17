"""`notifications.safety_alert` <- `safety.alert_raised`: conforto e fumo; resolução expira."""

import re
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, replace, stable_id
from homemind.contracts.notification import (
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    NotificationStatus,
    RefType,
)
from homemind.contracts.safety import SafetyAlert, SafetyAlertStatus
from homemind.features.notifications.handlers import SAFETY_ALERT_CONSUMER
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


def _event(alert: SafetyAlert, **kw) -> de.SafetyAlertRaised:
    """Como o produtor (`safety/engine._wrap`): id do evento derivado do alerta e do estado."""
    kw.setdefault("id", stable_id("safety-event", str(alert.id), alert.status.value))
    return de.SafetyAlertRaised(
        ts=alert.resolved_at or alert.started_at,
        household_id=alert.household_id,
        provenance=alert.provenance,
        data=alert,
        **kw,
    )


def _resolved(alert: SafetyAlert) -> SafetyAlert:
    return replace(
        alert,
        status=SafetyAlertStatus.resolved,
        resolved_at=alert.started_at + timedelta(minutes=3),
    )


def _go(db, *events, **kw):
    return deliver(db, SAFETY_ALERT_CONSUMER, *events, **kw)


def _no_leaks(text: str) -> None:
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text)  # sem UUIDs
    for forbidden in ("Aquecedor", "aquecedor do", "tomada", "sensor", "Bruno", "Diogo", "Quarto"):
        assert forbidden not in text


# --- janela aberta com aquecimento (conforto) --------------------------------------------------


def test_janela_numa_zona_comum_e_da_casa(seeded):
    assert _go(seeded, _event(fx.window_alert())) == [True]
    (n,) = all_notifications(seeded)
    assert n.kind is NotificationKind.comfort_alert
    assert n.scope is NotificationScope.household and n.recipient_resident_id is None
    assert n.severity is NotificationSeverity.warning
    assert n.actions == []  # sem botões por agora
    assert (n.ref.type, n.ref.id) == (RefType.safety_alert, fx.window_alert().id)
    assert "«Sala»" in n.body and "(SIMULADO)" in n.body
    _no_leaks(n.title + n.body)
    assert [v.kind for v in visible_to(seeded, fx.ANA)] == [NotificationKind.comfort_alert]
    assert [v.kind for v in visible_to(seeded, fx.DIOGO)] == [NotificationKind.comfort_alert]


def test_janela_no_quarto_com_inquilino_ativo_e_pessoal_desse_inquilino(seeded):
    alert = replace(fx.window_alert(), room_id=fx.ROOM_BRUNO)
    _go(seeded, _event(alert))
    (n,) = all_notifications(seeded)
    assert n.scope is NotificationScope.personal and n.recipient_resident_id == fx.BRUNO
    assert "do teu quarto" in n.body
    _no_leaks(n.title + n.body)
    assert len(visible_to(seeded, fx.BRUNO)) == 1
    for other in (fx.ANA, fx.CARLA, fx.LANDLORD, fx.OPERATOR):
        assert visible_to(seeded, other) == []
    (created,) = created_events(seeded)
    assert created.event.data.recipient_resident_id == fx.BRUNO


def test_quarto_sem_inquilino_ativo_cai_para_a_casa_sem_nomear_o_quarto(seeded):
    end_membership(seeded, fx.DIOGO)
    _go(seeded, _event(replace(fx.window_alert(), room_id=fx.ROOM_DIOGO)))
    (n,) = all_notifications(seeded)
    assert n.scope is NotificationScope.household
    assert n.body.startswith("Uma janela")
    _no_leaks(n.title + n.body)


def test_janela_sem_divisao_ou_com_divisao_desconhecida_e_da_casa(seeded):
    _go(
        seeded,
        _event(replace(fx.window_alert(), room_id=None, id=stable_id("safety", "sem-divisao"))),
        _event(
            replace(
                fx.window_alert(),
                room_id=stable_id("room", "nao-existe"),
                id=stable_id("safety", "x"),
            )
        ),
    )
    assert [n.scope for n in all_notifications(seeded)] == [NotificationScope.household] * 2


def test_origem_real_nao_diz_simulado(seeded):
    _go(seeded, _event(replace(fx.window_alert(), provenance=REAL)))
    (n,) = all_notifications(seeded)
    assert n.origin is Origin.real and "SIMULADO" not in n.body


# --- fumo -------------------------------------------------------------------------------------


def test_fumo_e_alerta_critico_da_casa_com_aviso_de_certificacao(seeded):
    _go(seeded, _event(fx.smoke_alert()))
    (n,) = all_notifications(seeded)
    assert n.kind is NotificationKind.security_alert
    assert n.scope is NotificationScope.household
    assert n.severity is NotificationSeverity.critical
    assert n.actions == []
    assert "não substitui um detetor de fumo certificado" in n.body and "112" in n.body
    for cut in ("desligar", "cortar", "tomada"):  # fumo nunca sugere cortes
        assert cut not in n.body.lower()
    _no_leaks(n.title + n.body)
    assert len(visible_to(seeded, fx.ANA)) == 1


def test_fumo_numa_zona_comum_diz_qual(seeded):
    _go(seeded, _event(replace(fx.smoke_alert(), room_id=fx.ROOM_SALA)))
    (n,) = all_notifications(seeded)
    assert "«Sala»" in n.body


def test_senhorio_continua_sem_ver_nem_com_notify_landlord(seeded):
    alert = fx.smoke_alert()
    assert alert.notify_landlord is True
    _go(seeded, _event(alert), _event(fx.window_alert()))
    assert len(all_notifications(seeded)) == 2
    assert visible_to(seeded, fx.LANDLORD) == []  # allow-list só `info`
    assert visible_to(seeded, fx.OPERATOR) == []


# --- idempotência e resolução -----------------------------------------------------------------


def test_reentrega_e_idempotente(seeded):
    assert _go(seeded, _event(fx.window_alert()), twice=True) == [True, False]
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


def test_o_mesmo_alerta_com_outro_id_de_evento_nao_duplica(seeded):
    again = _event(fx.smoke_alert(), id=stable_id("outro-evento"))
    assert _go(seeded, _event(fx.smoke_alert()), again) == [True, True]
    assert len(all_notifications(seeded)) == 1
    assert len(created_events(seeded)) == 1


@pytest.mark.parametrize("alert_fn", [fx.window_alert, fx.smoke_alert])
def test_resolvido_expira_as_abertas_sem_evento(seeded, alert_fn):
    alert = alert_fn()
    _go(seeded, _event(alert))
    before = len(created_events(seeded))
    _go(seeded, _event(_resolved(alert)))
    (n,) = all_notifications(seeded)
    assert n.status is NotificationStatus.expired
    assert len(created_events(seeded)) == before  # sem eventos novos
    # e uma reentrega tardia do «ativo» não a ressuscita nem a duplica
    _go(seeded, _event(alert, id=stable_id("tardio")))
    (n,) = all_notifications(seeded)
    assert n.status is NotificationStatus.expired


def test_resolvido_expira_tambem_a_ja_lida_e_a_pessoal(seeded):
    alert = replace(fx.window_alert(), room_id=fx.ROOM_BRUNO)
    _go(seeded, _event(alert))
    nid = all_notifications(seeded)[0].id
    from homemind.features.notifications.directory import SqliteResidentDirectory
    from homemind.features.notifications.service import NotificationService
    from homemind.features.notifications.sqlite import SqliteNotificationRepository

    seeded.run_sync(
        lambda c: NotificationService(
            SqliteNotificationRepository(c), SqliteResidentDirectory(c), lambda: NOW
        ).mark_read(nid, household_id=fx.HOUSEHOLD, resident_id=fx.BRUNO)
    )
    assert all_notifications(seeded)[0].status is NotificationStatus.read
    _go(seeded, _event(_resolved(alert)))
    assert all_notifications(seeded)[0].status is NotificationStatus.expired


def test_resolvido_so_toca_nas_do_proprio_alerta(seeded):
    other = replace(fx.window_alert(), id=stable_id("safety", "outra"))
    _go(seeded, _event(fx.window_alert()), _event(other))
    _go(seeded, _event(_resolved(fx.window_alert())))
    by_ref = {str(n.ref.id): n.status for n in all_notifications(seeded)}
    assert by_ref[str(fx.window_alert().id)] is NotificationStatus.expired
    assert by_ref[str(other.id)] is NotificationStatus.unread


def test_resolvido_sem_notificacao_previa_e_um_no_op(seeded):
    assert _go(seeded, _event(_resolved(fx.window_alert()))) == [True]
    assert all_notifications(seeded) == []
    assert created_events(seeded) == []


def test_alerta_de_outra_casa_nao_toca_nesta(seeded):
    from homemind.features.notifications.tests.conftest import HOUSE_B

    other = replace(fx.smoke_alert(), household_id=HOUSE_B)
    ev = de.SafetyAlertRaised(
        ts=fx.T0, household_id=HOUSE_B, provenance=other.provenance, data=other
    )
    _go(seeded, ev)
    assert all_notifications(seeded) == []
    assert len(all_notifications(seeded, HOUSE_B)) == 1
