"""App real (com o lifespan da retenção) e base em memória com as casas SIMULADAS."""

import pytest
from fastapi.testclient import TestClient

from homemind.features.households.tests.conftest import seed_two_houses


@pytest.fixture
def app():
    from homemind.main import app as real_app

    with TestClient(real_app):
        real_app.state.db.run_sync(seed_two_houses)
        yield real_app
