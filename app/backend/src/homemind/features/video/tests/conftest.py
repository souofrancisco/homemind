"""App real com base em memória (casa demo) e utilizadores simulados, sem Authentik."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.core.access import get_clock
from homemind.features.auth.service import User, current_user
from homemind.features.households.repo import seed_demo

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def client():
    from homemind.main import app

    def fake_user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(sub=sub)

    app.dependency_overrides[current_user] = fake_user
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    with TestClient(app) as c:
        app.state.db.run_sync(seed_demo)
        yield c
    app.dependency_overrides.clear()
