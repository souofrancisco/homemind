"""Ponta a ponta billing real <-> notificações reais (sem mocks de billing). Tudo SIMULADO.

Os produtores são os verdadeiros (atribuidor, expiração e fecho do mês de `billing`) e os
consumidores são os de `notifications`, ligados pelo barramento da app. Só o relógio e a
autenticação são substituídos, como nos testes de cada feature.
"""

import re
import time
from datetime import timedelta

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import cost_cents, replace
from homemind.contracts.energy import ConsumptionStatus, CostEstimate
from homemind.core.access import get_clock
from homemind.features.auth.service import User, current_user
from homemind.features.billing.router import run_expiry
from homemind.features.notifications.tests.conftest import NOW, seed_two_houses

TS = fx.T0 + timedelta(minutes=30)
H = fx.HOUSEHOLD
NOTIFS = f"/api/households/{H}/notifications"
BILLS = f"/api/households/{H}/bills"
SUB = {fx.ANA: "sub-ana", fx.BRUNO: "sub-bruno", fx.CARLA: "sub-carla", fx.DIOGO: "sub-diogo"}
LANDLORD = "sub-senhorio"


def as_(sub: str) -> dict[str, str]:
    return {"x-test-sub": sub}


@pytest.fixture
def now():
    return {"value": NOW}


@pytest.fixture
def client(now):
    from homemind.main import app

    def fake_user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(sub=sub)

    app.dependency_overrides[current_user] = fake_user
    app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    with TestClient(app) as c:
        app.state.db.run_sync(seed_two_houses)
        yield c
    app.dependency_overrides.clear()


def _wait(predicate, what: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu a tempo: {what}")


def _list(client, sub: str, **params) -> list[dict]:
    r = client.get(NOTIFS, headers=as_(sub), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _by_title(client, sub: str, title: str) -> list[dict]:
    return [n for n in _list(client, sub) if n["title"] == title]


def _sala_consumption(wh: int = 5000):
    """Aquecedor na sala; 5 kWh = 0,80 € (acima do limiar de 0,50 €: pergunta-se)."""
    cost = CostEstimate(
        cents=cost_cents(wh, fx.PRICE_MILLICENTS), price_millicents_per_kwh=fx.PRICE_MILLICENTS
    )
    return replace(fx.consumption(closed=True), energy_wh=wh, cost_estimate=cost)


def _publish_consumption(client, c) -> None:
    assert c.status is ConsumptionStatus.closed
    client.app.state.bus.publish_threadsafe(
        de.EnergyConsumptionClosed(ts=TS, household_id=H, provenance=c.provenance, data=c)
    )


def _vote_notification(client) -> dict:
    """A notificação «De quem é esta conta?» como a Carla a recebe (produzida por billing)."""
    (n,) = _wait(
        lambda: [n for n in _list(client, SUB[fx.CARLA]) if n["kind"] == "confirmation_request"],
        "notificação de voto",
    )
    return n


def _respond(client, who, n, action_id, **body):
    r = client.post(
        f"{NOTIFS}/{n['id']}/respond",
        json={"action_id": action_id, **body},
        headers=as_(SUB[who]),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_e_minha_da_carla_regista_so_na_conta_da_carla(client, now):
    now["value"] = TS + timedelta(minutes=1)
    _publish_consumption(client, _sala_consumption())
    n = _vote_notification(client)
    assert n["voting"]["eligible"] == 4
    for who in (fx.ANA, fx.BRUNO, fx.DIOGO):  # os 4 inquilinos são perguntados
        assert any(x["kind"] == "confirmation_request" for x in _list(client, SUB[who]))
    assert _list(client, LANDLORD) == []

    _respond(client, fx.CARLA, n, "mine")

    (info,) = _wait(
        lambda: _by_title(client, SUB[fx.CARLA], "Registado na tua conta"), "info da Carla"
    )
    assert info["kind"] == "info" and info["status"] == "unread" and info["actions"] == []
    assert "(SIMULADO)" in info["body"]
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", info["title"] + info["body"])
    for sub in (SUB[fx.ANA], SUB[fx.BRUNO], SUB[fx.DIOGO], LANDLORD):
        titles = {x["title"] for x in _list(client, sub)}
        assert not titles & {"Registado na tua conta", "Dividido por todos"}


def test_dica_de_dono_nao_preseleciona_o_voto_nem_chega_ao_senhorio(client, now):
    now["value"] = TS + timedelta(minutes=1)
    _publish_consumption(client, _sala_consumption())
    n = _vote_notification(client)
    assert "Parece ser do Bruno (aparelho identificado a 90 %); confirma (SIMULADO)." in n["body"]
    assert not any(name in n["body"] for name in ("Ana", "Carla", "Diogo"))
    assert not any(term in n["body"].casefold() for term in ("presença", "em casa", "fora"))
    assert n["status"] == "unread" and n["can_respond"] is True
    assert [a["id"] for a in n["actions"]] == ["mine", "other", "unknown"]
    assert _list(client, LANDLORD) == []

    # Mesmo com a dica para Bruno, a decisão segue o voto explícito de Ana (D-32).
    _respond(client, fx.ANA, n, "mine")
    (info,) = _wait(
        lambda: _by_title(client, SUB[fx.ANA], "Registado na tua conta"),
        "atribuição à moradora que votou mine",
    )
    assert info["kind"] == "info"
    assert _by_title(client, SUB[fx.BRUNO], "Registado na tua conta") == []


def test_inconclusivo_expirado_divide_por_todos_a_cada_votante(client, now):
    now["value"] = TS + timedelta(minutes=1)
    _publish_consumption(client, _sala_consumption())
    n = _vote_notification(client)
    _respond(client, fx.ANA, n, "unknown")
    _respond(client, fx.BRUNO, n, "unknown")
    assert _by_title(client, SUB[fx.ANA], "Dividido por todos") == []  # ainda a votar

    late = TS + timedelta(hours=25)
    now["value"] = late
    assert client.portal.call(run_expiry, client.app.state.db, client.app.state.bus, late) >= 1

    for who in (fx.ANA, fx.BRUNO):
        (info,) = _wait(
            lambda who=who: _by_title(client, SUB[who], "Dividido por todos"), "info de votante"
        )
        assert info["kind"] == "info" and "(SIMULADO)" in info["body"]
    # quem não votou não recebe (nem o senhorio)
    time.sleep(0.3)
    for sub in (SUB[fx.CARLA], SUB[fx.DIOGO], LANDLORD):
        assert _by_title(client, sub, "Dividido por todos") == []


def test_fecho_do_mes_avisa_so_o_dono_de_cada_parcela_sem_valores(client, now):
    now["value"] = now["value"].replace(month=12, day=5)
    body = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    r = client.post(BILLS, json=body, headers=as_(LANDLORD))
    assert r.status_code == 201, r.text
    bill_id = r.json()["id"]
    assert client.post(f"{BILLS}/{bill_id}/finalize", headers=as_(LANDLORD)).status_code == 200

    receipts = {}
    for who in (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO):
        (n,) = _wait(
            lambda who=who: _by_title(client, SUB[who], "Recibo disponível"), "recibo disponível"
        )
        receipts[who] = n
        assert n["kind"] == "info" and n["actions"] == [] and "(SIMULADO)" in n["body"]
        assert "€" not in n["title"] + n["body"]  # o valor é da app, não da notificação
        assert not re.search(r"\d", n["title"] + n["body"])
        mine = client.get(f"{BILLS}/{bill_id}/receipt", headers=as_(SUB[who])).json()
        assert n["ref"] == {"type": "allocation", "id": mine["id"]}  # o ref aponta ao SEU recibo
    assert len({n["ref"]["id"] for n in receipts.values()}) == 4  # um por parcela
    assert _by_title(client, LANDLORD, "Recibo disponível") == []
