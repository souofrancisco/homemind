"""Fixtures dos testes de energia.

- `app`, `client`, `now`: a app real com BD em memória do billing (runtime e `/energy/overview`).
- `db`: BD SQLite temporária com duas casas (aprendizagem e assinaturas, ENERGY-01).
"""

import pytest

from homemind.core.db import Database, migrate
from homemind.features.billing.tests.conftest import app, client, now  # noqa: F401
from homemind.features.households.tests.conftest import seed_two_houses


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "learning.sqlite3")
    database.open()
    migrate(database)
    database.run_sync(seed_two_houses)
    try:
        yield database
    finally:
        database.close()
