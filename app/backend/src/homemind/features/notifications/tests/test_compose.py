from datetime import timedelta

import pytest
from pydantic import ValidationError

from homemind.contracts.common import Origin
from homemind.contracts.notification import (
    ConfirmationChoice,
    ConfirmationRequest,
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    RefType,
)
from homemind.features.notifications.compose import (
    CONFIRMATION_LABELS,
    compose_budget_alert,
    compose_confirmation,
    event_id_for,
    notification_id_for,
)
from homemind.features.notifications.tests._fakes import (
    ANA,
    BRUNO,
    HOUSE,
    T0,
    confirmation_request,
    uid,
)
from homemind.features.notifications.text import format_eur


def _confirmation(req=None, origin=Origin.real, source="evento-1"):
    return compose_confirmation(
        req or confirmation_request(),
        household_id=HOUSE,
        responder_ids=[ANA, BRUNO],
        origin=origin,
        correlation_id=uid("corr"),
        source_event_id=uid(source),
        now=T0,
    )


def _budget(**over):
    kwargs = {
        "household_id": HOUSE,
        "resident_id": ANA,
        "budget_id": uid("orcamento"),
        "pct": 80,
        "spent_cents": 2000,
        "limit_cents": 2500,
        "forecast_cents": 3100,
        "origin": Origin.real,
        "correlation_id": uid("corr"),
        "source_event_id": uid("limiar-80"),
        "now": T0,
    }
    return compose_budget_alert(**(kwargs | over))


@pytest.mark.parametrize(
    ("cents", "text"),
    [
        (0, "0,00 €"),
        (5, "0,05 €"),
        (64, "0,64 €"),
        (2000, "20,00 €"),
        (123456, "1 234,56 €"),
        (100000000, "1 000 000,00 €"),
    ],
)
def test_format_eur(cents, text):
    assert format_eur(cents) == text


def test_ids_deterministicos_e_distintos():
    a = notification_id_for(uid("e1"), NotificationKind.confirmation_request)
    assert a == notification_id_for(uid("e1"), NotificationKind.confirmation_request)
    assert a != notification_id_for(uid("e2"), NotificationKind.confirmation_request)
    assert a != notification_id_for(uid("e1"), NotificationKind.budget_alert)
    assert event_id_for("notification.created", a) != event_id_for("notification.responded", a)
    assert event_id_for("notification.created", a) == event_id_for("notification.created", a)


def test_confirmacao_estrutura_e_texto():
    n = _confirmation()
    assert n.scope is NotificationScope.household
    assert n.kind is NotificationKind.confirmation_request
    assert n.title == "De quem é esta conta?"
    assert n.body == "O aquecedor está ligado numa zona comum, cerca de 0,64 € estimados."
    assert [a.id for a in n.actions] == ["mine", "everyone", "unknown", "other"]
    assert [a.label for a in n.actions] == list(CONFIRMATION_LABELS.values())
    assert [a.style.value for a in n.actions] == ["primary", "neutral", "neutral", "neutral"]
    assert n.responder_ids == [ANA, BRUNO]
    assert n.expires_at == T0 + timedelta(hours=24)
    assert n.ref is not None
    assert (n.ref.type, n.ref.id) == (RefType.consumption_event, uid("consumo-1"))


def test_confirmacao_sem_nome_nem_custo_e_simulada():
    n = _confirmation(confirmation_request(name=None, cost=None), origin=Origin.simulated)
    assert n.body == "Um aparelho está ligado numa zona comum (SIMULADO)."
    assert "estimados" not in n.body


def test_confirmacao_com_dica_inferencial_e_confianca_arredondada():
    req = confirmation_request().model_copy(
        update={"likely_owner_resident_id": BRUNO, "match_confidence": 0.874}
    )
    # O nome só é inserido pelo serviço depois de o validar no diretório.
    n = compose_confirmation(
        req,
        household_id=HOUSE,
        responder_ids=[ANA, BRUNO],
        origin=Origin.real,
        correlation_id=uid("corr"),
        source_event_id=uid("dica"),
        now=T0,
        likely_owner_name="Bruno",
    )
    assert n.body == (
        "O aquecedor está ligado numa zona comum, cerca de 0,64 € estimados. "
        "Parece ser do Bruno (aparelho identificado a 87 %); confirma."
    )


@pytest.mark.parametrize(
    ("owner", "confidence", "eligible"),
    [
        (BRUNO, None, [ANA, BRUNO]),
        (None, 0.9, [ANA, BRUNO]),
        (uid("nao-elegivel"), 0.9, [ANA, BRUNO]),
    ],
    ids=["dono-sem-confianca", "confianca-sem-dono", "dono-fora-dos-elegiveis"],
)
def test_contrato_rejeita_dica_incoerente(owner, confidence, eligible):
    base = confirmation_request(eligible=eligible).model_dump()
    with pytest.raises(ValidationError):
        ConfirmationRequest(
            **(base | {"likely_owner_resident_id": owner, "match_confidence": confidence})
        )


def test_confirmacao_omite_dica_sem_nome_e_nao_repete_nome_no_aparelho():
    req = confirmation_request(name="Aquecedor do bruno").model_copy(
        update={"likely_owner_resident_id": BRUNO, "match_confidence": 0.9}
    )
    kwargs = {
        "household_id": HOUSE,
        "responder_ids": [ANA, BRUNO],
        "origin": Origin.real,
        "correlation_id": uid("corr"),
        "source_event_id": uid("dica-sem-nome"),
        "now": T0,
    }
    without_name = compose_confirmation(req, **kwargs)
    assert "Parece" not in without_name.body and "identificado" not in without_name.body
    with_name = compose_confirmation(
        req,
        **(kwargs | {"source_event_id": uid("dica-duplicada")}),
        likely_owner_name="BRUNO",
    )
    assert with_name.body.endswith("Aparelho identificado a 90 %.")
    assert "Parece" not in with_name.body


def test_confirmacao_respeita_a_ordem_das_opcoes():
    req = confirmation_request().model_copy(
        update={"options": [ConfirmationChoice.unknown, ConfirmationChoice.mine]}
    )
    assert [a.id for a in _confirmation(req).actions] == ["unknown", "mine"]


def test_confirmacao_sem_ids_no_texto():
    n = _confirmation()
    text = f"{n.title} {n.body} {' '.join(a.label for a in n.actions)}"
    for forbidden in (str(uid("consumo-1")), str(HOUSE), "http", "-"):
        assert forbidden not in text


def test_confirmacao_expirada_nao_compoe():
    with pytest.raises(ValidationError):
        _confirmation(confirmation_request(expires_in=timedelta(hours=-1)))


def test_alerta_orcamento_texto_e_severidade():
    n = _budget()
    assert n.scope is NotificationScope.personal
    assert n.recipient_resident_id == ANA
    assert n.actions == []
    assert n.severity is NotificationSeverity.warning
    assert (
        n.body == "Já gastaste 20,00 € dos teus 25,00 € (80 %). Ao ritmo atual chegas aos 31,00 €."
    )
    assert n.ref is not None
    assert (n.ref.type, n.ref.id) == (RefType.budget, uid("orcamento"))


def test_alerta_orcamento_sem_previsao_nem_limite():
    n = _budget(pct=50, forecast_cents=None, limit_cents=None)
    assert n.severity is NotificationSeverity.info
    assert n.body == "Já gastaste 20,00 € (50 %)."


def test_alerta_orcamento_limiar_79_e_info_e_100_e_warning():
    assert _budget(pct=79).severity is NotificationSeverity.info
    assert _budget(pct=100).severity is NotificationSeverity.warning


def test_alerta_orcamento_simulado():
    assert _budget(origin=Origin.simulated).body.endswith("(SIMULADO)")
