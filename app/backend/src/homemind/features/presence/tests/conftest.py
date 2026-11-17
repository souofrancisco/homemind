"""Presença: base em memória com as casas de teste, relógio controlado e Wi-Fi SIMULADO.
Os «MACs» são fictícios (faixa 02:00:00:… de administração local)."""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.core.access import get_clock
from homemind.core.config import get_settings
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus
from homemind.features.auth.service import User, current_user
from homemind.features.households.tests.conftest import HOUSE_B, NOW, seed_two_houses
from homemind.features.presence.service import PresenceService

SALT = "sal-de-teste-nao-secreto"
TOKEN = "token-de-teste-do-anfitriao"
MAC_BRUNO = "02:00:00:aa:00:01"
MAC_CARLA = "02:00:00:aa:00:02"
MAC_VISITA = "02:00:00:bb:00:99"
A, B = str(fx.HOUSEHOLD), str(HOUSE_B)


def set_presence_opt_in(db: Database, resident, value: int) -> None:
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET presence_opt_in = ? WHERE resident_id = ?",
            (value, str(resident)),
        )
    )


def seed_with_opt_in(conn) -> None:
    """Casas de teste; o Bruno (inquilino nas duas) já aceitou a presença (2.º consentimento)."""
    seed_two_houses(conn)
    conn.execute(
        "UPDATE membership SET presence_opt_in = 1 WHERE resident_id = ?", (str(fx.BRUNO),)
    )


def as_(sub: str) -> dict[str, str]:
    return {"x-test-sub": sub}


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("PRESENCE_MATCH_SALT", SALT)
    monkeypatch.setenv("PRESENCE_WIFI_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("PRESENCE_WIFI_MODE", "ingest")
    monkeypatch.setenv("PRESENCE_INGEST_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(settings_env, clock):
    from homemind.main import app

    def fake_user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(sub=sub)

    app.dependency_overrides[current_user] = fake_user
    app.dependency_overrides[get_clock] = lambda: clock
    with TestClient(app) as c:
        app.state.db.run_sync(seed_with_opt_in)
        c.app_state = app.state
        c.clock = clock
        app.state.presence.clock = clock  # o serviço lê o relógio no arranque
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def world(clock):
    """Base, barramento (sem consumidores) e serviço soltos, para testes assíncronos."""
    db = Database(":memory:")
    db.open()
    migrate(db)
    db.run_sync(seed_with_opt_in)
    bus = EventBus(db)
    service = PresenceService(db, bus, salt=SALT, clock=clock)
    yield service
    db.close()


def cues(db: Database, source: str | None = None) -> list:
    from homemind.core.events import load_events

    out = [s.event for s in db.run_sync(lambda c: load_events(c, types=["presence.cue_recorded"]))]
    return [e for e in out if source is None or e.data.source.value == source]


def dump_text(db: Database) -> str:
    """Todo o texto de todas as tabelas: para provar que um MAC ou hash nunca ficou lá."""

    def run(conn):
        parts = []
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for row in conn.execute(f"SELECT * FROM {name}"):  # noqa: S608 - nomes do esquema
                parts.append(" ".join(str(v) for v in tuple(row)))
        return "\n".join(parts)

    return db.run_sync(run)
