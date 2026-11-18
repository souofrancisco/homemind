"""ENERGY-04 de ponta a ponta: BD SQLite real (tmp_path), barramento real, relógio fixo.

Sessões simuladas desconhecidas -> `energy.identification_needed` -> notificação da casa ->
resposta -> aparelho + assinatura `learned`; desfazer revoga amostras sem tocar no histórico.
"""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.devices import SignaturePattern
from homemind.contracts.domain_events import (
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
    EnergyReadingRecorded,
    NotificationResponded,
    NotificationRespondedData,
)
from homemind.contracts.notification import (
    AlreadyRespondedError,
    NotificationKind,
    NotificationRef,
    NotificationResponse,
    RefType,
)
from homemind.core.access import get_clock
from homemind.core.errors import register_errors
from homemind.core.events import EventBus, append_event, load_events
from homemind.features.appliances import repo
from homemind.features.auth.service import User, current_user
from homemind.features.energy.classifier import SessionFeatures, classify
from homemind.features.energy.identification_consumer import (
    INPUT_TYPES,
    make_identification_consumer,
)
from homemind.features.energy.learning_consumer import INPUT_TYPES as LEARNING_TYPES
from homemind.features.energy.learning_consumer import make_learning_consumer
from homemind.features.energy.signatures import signatures_router
from homemind.features.energy.tests.test_learning_consumer import add_appliance
from homemind.features.households.tests.conftest import NOW, as_
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.handlers import (
    IDENTIFICATION_CONSUMER,
    IDENTIFICATION_EVENT_TYPES,
    make_identification_handler,
)
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository

DAY = timedelta(days=1)


class Harness:
    """Barramento real com a identificação, a aprendizagem e o consumidor de notificações."""

    def __init__(self, db):
        self.db = db
        self.now = NOW
        self.bus = EventBus(db)
        catalog = repo.appliance_catalog()
        self.subs = {
            "energy.identification": INPUT_TYPES,
            "energy.learning": LEARNING_TYPES,
            IDENTIFICATION_CONSUMER: list(IDENTIFICATION_EVENT_TYPES),
        }
        self.bus.subscribe(
            "energy.identification", make_identification_consumer(catalog), INPUT_TYPES
        )
        self.bus.subscribe("energy.learning", make_learning_consumer(catalog), LEARNING_TYPES)
        self.bus.subscribe(
            IDENTIFICATION_CONSUMER,
            make_identification_handler(lambda: self.now),
            IDENTIFICATION_EVENT_TYPES,
        )

    def drain(self) -> None:
        async def go():
            progressed = True
            while progressed:
                progressed = False
                for name, types in self.subs.items():
                    for stored in self.db.run_sync(lambda c, t=types: load_events(c, types=t)):
                        progressed |= await self.bus.deliver(name, stored)

        asyncio.run(go())

    def session(self, day: float, *, watts=800, minutes=20, key=None) -> None:
        """Sessão desconhecida simulada (sem aparelho nem candidatos) na tomada da sala."""
        start = NOW + day * DAY
        key = key or f"{day}-{watts}"
        sid = stable_id("identification-session", key)
        ongoing = replace(
            fx.consumption(),
            id=sid,
            started_at=start,
            ended_at=None,
            status="ongoing",
            peak_w=watts,
            match={"candidates": []},
            appliance_owner_resident_id=None,
            cost_estimate=None,
        )
        events = []
        for seconds, power in ((0, watts + 100), (minutes * 60, 100)):
            at = start + timedelta(seconds=seconds)
            r = replace(fx.reading(power, at), id=stable_id(str(sid), str(seconds)))
            events.append(
                EnergyReadingRecorded(
                    ts=at, household_id=fx.HOUSEHOLD, provenance=r.provenance, data=r
                )
            )
            if seconds == 0:
                events.append(
                    EnergyConsumptionDetected(
                        ts=at,
                        household_id=fx.HOUSEHOLD,
                        provenance=ongoing.provenance,
                        data=ongoing,
                    )
                )
        closed = replace(
            ongoing, status="closed", ended_at=start + timedelta(minutes=minutes), energy_wh=300
        )
        events.append(
            EnergyConsumptionClosed(
                ts=closed.ended_at,
                household_id=fx.HOUSEHOLD,
                provenance=closed.provenance,
                data=closed,
            )
        )
        self.now = closed.ended_at + timedelta(minutes=1)

        def write(c):
            for e in events:
                append_event(c, e)

        self.db.run_sync(write)
        self.drain()

    def requests(self):
        return self.db.run_sync(lambda c: load_events(c, types=["energy.identification_needed"]))

    def notifications(self):
        return [
            n
            for n in self.db.run_sync(
                lambda c: SqliteNotificationRepository(c).list_household(fx.HOUSEHOLD)
            )
            if n.kind is NotificationKind.appliance_identification
        ]

    def service(self, c):
        return NotificationService(
            SqliteNotificationRepository(c), SqliteResidentDirectory(c), lambda: self.now
        )

    def answer(self, action: str, by=fx.ANA) -> None:
        n = self.notifications()[-1]

        def respond(c):
            out = self.service(c).respond(
                n.id, household_id=fx.HOUSEHOLD, resident_id=by, action_id=action
            )
            for e in out.events:  # como a rota: na mesma transação
                append_event(c, e)

        self.db.run_sync(respond)
        self.drain()

    def appliances(self):
        return self.db.run_sync(
            lambda c: c.execute(
                "SELECT a.*,s.scope,s.owner_resident_id FROM appliance a JOIN appliance_state s"
                " ON s.appliance_id=a.id WHERE a.household_id=? AND a.category='other'",
                (str(fx.HOUSEHOLD),),
            ).fetchall()
        )

    def signatures(self):
        return self.db.run_sync(lambda c: repo.signatures_for_household(c, fx.HOUSEHOLD))

    def samples(self, where="1=1"):
        return self.db.run_sync(
            lambda c: c.execute(
                f"SELECT * FROM energy_signature_sample WHERE {where} ORDER BY created_at,id"
            ).fetchall()
        )


@pytest.fixture
def h(db):
    return Harness(db)


def asked_three_times(h) -> None:
    for day in (0, 1, 2):
        h.session(day)


def test_third_similar_session_asks_once_and_only_tenants(h):
    h.session(0)
    h.session(1, watts=830, minutes=25)  # parecida: dentro de 10 % e duração >= metade
    assert h.requests() == [] and h.notifications() == []
    h.session(1.5, watts=2000)  # outra carga: outro grupo, não conta
    h.session(2, watts=790)
    [stored] = h.requests()
    req = stored.event.data
    assert req.occurrences == 3 and req.hour_local == 12 and req.approx_power_w == 800
    [n] = h.notifications()
    assert n.title == "O que é este aparelho?"
    assert (
        n.body == "Um aparelho de ~800 W liga muitas vezes por volta das 12h. O que é? (SIMULADO)"
    )
    assert [a.id for a in n.actions] == ["mine", "household", "ignore"]
    assert [a.label for a in n.actions] == ["É meu", "É da casa", "Ignorar"]
    assert n.ref == NotificationRef(type=RefType.appliance_identification, id=req.id)
    assert set(n.responder_ids) == set(fx.TENANTS) and fx.LANDLORD not in n.responder_ids
    visible = h.db.run_sync(lambda c: h.service(c).list_for(fx.HOUSEHOLD, fx.LANDLORD))
    assert visible == []  # o senhorio nem vê a pergunta (hábitos dos inquilinos)
    assert h.db.run_sync(lambda c: h.service(c).list_for(fx.HOUSEHOLD, fx.BRUNO))
    for day in (3, 4):  # 4.ª e 5.ª: sem nova pergunta
        h.session(day)
    assert len(h.requests()) == 1 and len(h.notifications()) == 1


def test_mine_creates_personal_appliance_and_classifier_uses_it(h):
    asked_three_times(h)
    h.answer("mine", by=fx.ANA)
    [appliance] = h.appliances()
    assert appliance["name"] == "Aparelho ~800 W" and appliance["category"] == "other"
    assert appliance["scope"] == "personal" and appliance["owner_resident_id"] == str(fx.ANA)
    assert appliance["registered_by_resident_id"] == str(fx.ANA)
    assert appliance["typical_watts"] == 800
    aid = next(iter(h.signatures()))
    [sig] = h.signatures()[aid]
    assert str(aid) == appliance["id"]
    assert sig.origin.value == "learned" and sig.samples == 3 and sig.watts_mean == 800
    assert sig.pattern is SignaturePattern.continuous and sig.typical_hours == [12]
    samples = h.samples()
    assert len(samples) == 3 and {s["origin_kind"] for s in samples} == {"confirmation"}
    match = classify(SessionFeatures(800, 12, 1200, SignaturePattern.continuous), h.signatures())
    assert match.appliance_id == aid  # a resposta mudou as hipóteses futuras
    # A próxima sessão parecida é explicada pelo aparelho: aprende (ENERGY-01) e não pergunta.
    h.session(3)
    [sig] = h.signatures()[aid]
    assert sig.samples == 4 and len(h.requests()) == 1
    assert [s["origin_kind"] for s in h.samples()].count("learning") == 1


def test_second_answer_does_not_create_a_second_appliance(h):
    asked_three_times(h)
    h.answer("mine", by=fx.ANA)
    with pytest.raises(AlreadyRespondedError):
        h.answer("household", by=fx.BRUNO)  # a notificação fecha à primeira resposta
    # Mesmo que chegue outra resposta (reentrega), a energia já fechou o pedido.
    req = h.requests()[0].event.data
    late = NotificationResponded(
        ts=h.now,
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED,
        data=NotificationRespondedData(
            response=NotificationResponse(
                notification_id=h.notifications()[0].id,
                action_id="household",
                resident_id=fx.BRUNO,
                responded_at=h.now,
            ),
            ref=NotificationRef(type=RefType.appliance_identification, id=req.id),
        ),
    )
    h.db.run_sync(lambda c: append_event(c, late))
    h.drain()
    assert len(h.appliances()) == 1


def test_household_creates_common_appliance(h):
    asked_three_times(h)
    h.answer("household", by=fx.BRUNO)
    [appliance] = h.appliances()
    assert appliance["scope"] == "common" and appliance["owner_resident_id"] is None
    assert appliance["registered_by_resident_id"] == str(fx.BRUNO)
    assert len(h.signatures()) == 1


def test_ignore_snoozes_seven_days_then_can_ask_again(h):
    asked_three_times(h)
    h.answer("ignore")
    assert h.appliances() == [] and h.signatures() == {}
    for day in range(3, 10):  # pausa até dia 2 + 21 min + 7 dias
        h.session(day)
    assert len(h.requests()) == 1
    h.session(10)
    assert len(h.requests()) == 2 and len(h.notifications()) == 2


def test_unanswered_question_expires_and_snoozes(h):
    asked_three_times(h)  # expira 24 h depois do fim da 3.ª sessão, sem resposta
    for day in range(3, 10):
        h.session(day)
    assert len(h.requests()) == 1
    h.session(10.5)
    assert len(h.requests()) == 2
    statuses = h.db.run_sync(
        lambda c: [
            r[0]
            for r in c.execute(
                "SELECT status FROM energy_identification_request ORDER BY created_at"
            )
        ]
    )
    assert statuses == ["expired", "pending"]


def test_sessions_explained_by_registered_power_are_not_asked(h, db):
    add_appliance(db, name="Secador", watts=800)  # a ENERGY-01 explica-o pela potência
    asked_three_times(h)
    assert h.requests() == []


@pytest.fixture
def client(db):
    app = FastAPI()
    app.state.db = db
    app.state.appliance_catalog = repo.appliance_catalog()
    app.include_router(signatures_router, prefix="/api/households/{household_id}/energy")
    register_errors(app)

    def user(request: Request):
        return User(sub=request.headers.get("x-test-sub", "unknown"))

    app.dependency_overrides[current_user] = user
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    with TestClient(app) as test_client:
        yield test_client


def _base(house=fx.HOUSEHOLD):
    return f"/api/households/{house}/energy"


def _raw(db):
    """Leituras, consumos e eventos: o histórico bruto que desfazer nunca muda."""
    return db.run_sync(
        lambda c: [tuple(r) for r in c.execute("SELECT * FROM domain_event ORDER BY seq")]
    )


def test_revoke_identification_keeps_raw_history_and_recalculates(h, db, client):
    asked_three_times(h)
    h.answer("mine", by=fx.ANA)
    h.session(3)  # mais uma amostra, de aprendizagem
    aid = next(iter(h.signatures()))
    req = h.requests()[0].event.data
    before = _raw(db)
    url = f"{_base()}/identifications/{req.id}/revoke"
    assert client.post(url, headers=as_("sub-senhorio")).status_code == 403
    assert client.post(url, headers=as_("sub-operador")).status_code == 403
    assert client.post(url, headers=as_("sub-bruno")).status_code == 404  # pessoal da Ana
    assert client.post(f"{_base()}/identifications/{stable_id('x')}/revoke",
                       headers=as_("sub-ana")).status_code == 404  # fmt: skip
    done = client.post(url, headers=as_("sub-ana"))
    assert done.status_code == 200
    body = done.json()
    assert body["revoked_samples"] == 3 and body["signature"]["samples"] == 1
    assert client.post(url, headers=as_("sub-ana")).status_code == 409
    [sig] = h.signatures()[aid]
    assert sig.samples == 1  # só a amostra de aprendizagem conta
    assert len([s for s in h.samples() if s["revoked_at"] is not None]) == 3
    # Desfazer a última amostra: a assinatura deixa de existir e de influenciar a classificação.
    samples = client.get(f"{_base()}/signatures/{aid}/samples", headers=as_("sub-ana")).json()
    assert len(samples) == 4 and "hour_local" in samples[0]
    learning = next(s for s in samples if s["origin_kind"] == "learning")
    sample_url = f"{_base()}/signatures/{aid}/samples/{learning['id']}/revoke"
    assert client.post(sample_url, headers=as_("sub-bruno")).status_code == 404
    last = client.post(sample_url, headers=as_("sub-ana"))
    assert last.status_code == 200 and last.json()["signature"] is None
    assert client.post(sample_url, headers=as_("sub-ana")).status_code == 409
    assert h.signatures() == {}
    assert (
        classify(SessionFeatures(800, 12, 1200, SignaturePattern.continuous), {}).appliance_id
        is None
    )
    assert _raw(db) == before  # leituras, consumos e eventos intactos
    assert len(h.appliances()) == 1  # o aparelho fica (renomeia-se/retira-se pela API)


def test_samples_route_roles(h, client):
    asked_three_times(h)
    h.answer("household", by=fx.BRUNO)
    aid = next(iter(h.signatures()))
    url = f"{_base()}/signatures/{aid}/samples"
    assert client.get(url, headers=as_("sub-ana")).status_code == 200  # comum: todos os inquilinos
    assert client.get(url, headers=as_("sub-senhorio")).status_code == 403
    assert client.get(url, headers=as_("sub-operador")).status_code == 403
    # Comum: só quem o registou o pode corrigir (regras do PATCH).
    req = h.requests()[0].event.data
    revoke = f"{_base()}/identifications/{req.id}/revoke"
    assert client.post(revoke, headers=as_("sub-ana")).status_code == 403
    assert client.post(revoke, headers=as_("sub-bruno")).status_code == 200
