"""App real com base em memória e as casas SIMULADAS de `households` (sem Authentik)."""

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.core.access import get_clock
from homemind.features.auth.service import User, current_user
from homemind.features.households.tests.conftest import NOW, seed_two_houses


@pytest.fixture
def now():
    return {"value": NOW}


@pytest.fixture
def app(now):
    from homemind.main import app as real_app

    def fake_user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(sub=sub)

    real_app.dependency_overrides[current_user] = fake_user
    real_app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    with TestClient(real_app):
        real_app.state.db.run_sync(seed_two_houses)
        yield real_app
    real_app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)
