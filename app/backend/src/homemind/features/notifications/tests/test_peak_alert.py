"""Aviso de pico numa zona comum (ALERT-03): texto, «por identificar» e sem números inventados."""

from datetime import timedelta

from homemind.contracts import domain_events as de
from homemind.contracts.common import Origin
from homemind.contracts.household import RoomKind
from homemind.contracts.notification import (
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
)
from homemind.features.notifications.compose import compose_peak_alert
from homemind.features.notifications.tests._fakes import (
    HOUSE,
    T0,
    FakeClock,
    FakeDirectory,
    make_service,
    prov,
    uid,
)
from homemind.features.notifications.text import format_kw

SALA, QUARTO, AQUECEDOR = uid("sala"), uid("quarto-ana"), uid("aquecedor")


def _alert(**over):
    kwargs = {
        "kind": de.AlertKind.peak,
        "severity": NotificationSeverity.warning,
        "device_id": uid("tomada"),
        "room_id": SALA,
        "appliance_id": AQUECEDOR,
        "power_w": 2040.0,
        "since": T0 - timedelta(minutes=35),
    }
    return de.AlertRaisedData(**(kwargs | over))


def _service():
    directory = FakeDirectory(
        rooms={
            (HOUSE, SALA): ("Sala", RoomKind.common),
            (HOUSE, QUARTO): ("Ana", RoomKind.bedroom),
        },
        appliances={(HOUSE, AQUECEDOR): "Aquecedor"},
    )
    svc, repo, _ = make_service(directory=directory, clock=FakeClock(T0))
    return svc, repo


def _raise(svc, alert, source="pico-1"):
    return svc.on_peak_alert(
        alert,
        source_event_id=uid(source),
        ts=T0,
        household_id=HOUSE,
        correlation_id=uid("corr"),
        provenance=prov(),
    )


def test_format_kw():
    assert (format_kw(2040.0), format_kw(1501.0), format_kw(12345.0)) == (
        "2,0 kW",
        "1,5 kW",
        "12,3 kW",
    )


def test_pico_na_sala_com_aparelho_comum():
    svc, _ = _service()
    n = _raise(svc, _alert()).notification
    assert n is not None
    assert (n.kind, n.scope, n.severity) == (
        NotificationKind.peak_alert,
        NotificationScope.household,
        NotificationSeverity.warning,
    )
    assert n.title == "Pico de consumo na zona «Sala»"
    assert n.body == "A zona «Sala» está a gastar 2,0 kW há 35 min. Provavelmente: Aquecedor."
    assert n.actions == [] and n.recipient_resident_id is None


def test_sem_divisao_e_por_identificar_e_nao_nomeia_aparelho():
    svc, _ = _service()
    n = _raise(svc, _alert(room_id=None)).notification
    assert n is not None and n.title == "Pico de consumo por identificar"
    assert n.body == (
        "Uma tomada está a gastar 2,0 kW há 35 min. Ainda não sabemos em que zona está."
    )
    assert "Aquecedor" not in n.body


def test_nome_de_quarto_nunca_aparece():
    svc, _ = _service()
    n = _raise(svc, _alert(room_id=QUARTO)).notification
    assert n is not None and "Ana" not in n.title + n.body


def test_sem_potencia_ou_inicio_nao_avisa_e_outros_tipos_ignorados():
    svc, repo = _service()
    assert _raise(svc, _alert(power_w=None)).notification is None
    assert _raise(svc, _alert(since=None), "b").notification is None
    other = _alert(kind=de.AlertKind.forgotten_appliance)
    assert _raise(svc, other, "c").notification is None


def test_reentrega_do_mesmo_evento_mesmo_id():
    svc, _ = _service()
    a = _raise(svc, _alert()).notification
    b = _raise(svc, _alert()).notification
    assert a is not None and (b is None or b.id == a.id)


def test_compoe_simulado():
    n = compose_peak_alert(
        source_event_id=uid("x"),
        household_id=HOUSE,
        room=("Sala", RoomKind.common),
        appliance_name=None,
        power_w=1800.0,
        minutes=31,
        origin=Origin.simulated,
        correlation_id=uid("corr"),
        now=T0,
    )
    assert n.body == "A zona «Sala» está a gastar 1,8 kW há 31 min. (SIMULADO)"
