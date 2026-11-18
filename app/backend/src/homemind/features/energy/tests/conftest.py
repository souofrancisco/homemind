"""Fixtures partilhadas pelos testes de energia (BD SQLite temporária com duas casas)."""

import pytest

from homemind.core.db import Database, migrate
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
