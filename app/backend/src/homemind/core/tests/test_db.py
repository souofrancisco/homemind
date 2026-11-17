import sqlite3
import threading

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from homemind.core import db as dbmod
from homemind.core.config import get_settings
from homemind.core.db import Database, DatabaseClosedError, MigrationError, migrate
from homemind.core.lifespan import core_lifespan


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.sqlite3")
    d.open()
    migrate(d)
    yield d
    d.close()


def test_migrate_creates_schema_and_is_idempotent(db):
    names = {
        r["name"] for r in db.run_sync(lambda c: c.execute("SELECT name FROM schema_migration"))
    }
    assert {"0001_core_households.sql", "0002_core_events.sql"} <= names
    assert migrate(db) == []  # repetir não faz nada
    tables = {
        r["name"]
        for r in db.run_sync(
            lambda c: c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        )
    }
    assert {"domain_event", "processed_event", "event_failure", "household", "membership"} <= tables


def test_pragmas(db):
    assert db.run_sync(lambda c: c.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    assert db.run_sync(lambda c: c.execute("PRAGMA journal_mode").fetchone()[0]) == "wal"
    assert db.run_sync(lambda c: c.execute("PRAGMA busy_timeout").fetchone()[0]) == 5000


def test_reopen_keeps_data_and_migrations(tmp_path):
    path = tmp_path / "r.sqlite3"
    d = Database(path)
    d.open()
    migrate(d)
    d.run_sync(lambda c: c.execute("INSERT INTO resident VALUES ('r1','Ana',NULL,'x')"))
    d.close()
    d2 = Database(path)
    d2.open()
    assert migrate(d2) == []
    assert (
        d2.run_sync(lambda c: c.execute("SELECT display_name FROM resident").fetchone()[0]) == "Ana"
    )
    d2.close()


def test_foreign_keys_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(
            lambda c: c.execute("INSERT INTO room VALUES ('x','nao-existe','Q','bedroom',NULL)")
        )


def test_rollback_on_error(db):
    def boom(c):
        c.execute("INSERT INTO resident VALUES ('r1','Ana',NULL,'x')")
        raise ValueError

    with pytest.raises(ValueError):
        db.run_sync(boom)
    assert db.run_sync(lambda c: c.execute("SELECT count(*) FROM resident").fetchone()[0]) == 0


def test_unique_constraint(db):
    ins = lambda c: c.execute("INSERT INTO resident VALUES ('r1','Ana','sub-1','x')")  # noqa: E731
    db.run_sync(ins)
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: c.execute("INSERT INTO resident VALUES ('r2','Bia','sub-1','x')"))


def test_concurrent_writers_serialize(db):
    db.run_sync(lambda c: c.execute("CREATE TABLE n (v INTEGER)"))
    errors = []

    def work(i):
        try:
            for j in range(20):
                db.run_sync(lambda c, v=i * 100 + j: c.execute("INSERT INTO n VALUES (?)", (v,)))
        except Exception as e:  # noqa: BLE001 - o teste só quer saber se houve erro
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert db.run_sync(lambda c: c.execute("SELECT count(*) FROM n").fetchone()[0]) == 80


def test_closed_database_refuses(tmp_path):
    d = Database(tmp_path / "c.sqlite3")
    d.open()
    d.close()
    with pytest.raises(DatabaseClosedError):
        d.run_sync(lambda c: None)


def test_changed_applied_migration_is_an_error(db, tmp_path, monkeypatch):
    fake = tmp_path / "m"
    fake.mkdir()
    (fake / "0001_core_households.sql").write_text("SELECT 1;")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", fake)
    with pytest.raises(MigrationError, match="alterada"):
        migrate(db)


def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path, monkeypatch):
    fake = tmp_path / "m"
    fake.mkdir()
    (fake / "0001_x_ok.sql").write_text("CREATE TABLE a (v INTEGER);")
    (fake / "0002_x_bad.sql").write_text(
        "CREATE TABLE b (v INTEGER); INSERT INTO nao_existe VALUES (1);"
    )
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", fake)
    d = Database(tmp_path / "f.sqlite3")
    d.open()
    with pytest.raises(MigrationError):
        migrate(d)
    names = [r[0] for r in d.run_sync(lambda c: c.execute("SELECT name FROM schema_migration"))]
    tables = [r[0] for r in d.run_sync(lambda c: c.execute("SELECT name FROM sqlite_master"))]
    assert names == ["0001_x_ok.sql"] and "b" not in tables
    d.close()


def test_migration_names_are_validated(tmp_path, monkeypatch):
    fake = tmp_path / "m"
    fake.mkdir()
    (fake / "init.sql").write_text("SELECT 1;")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", fake)
    d = Database(":memory:")
    d.open()
    with pytest.raises(MigrationError, match="inválido"):
        migrate(d)
    d.close()


def test_domain_event_is_immutable(db):
    db.run_sync(
        lambda c: c.execute(
            "INSERT INTO household (id,name,timezone,source_kind,created_at)"
            " VALUES ('h','C','UTC','demo','x')"
        )
    )
    db.run_sync(
        lambda c: c.execute(
            "INSERT INTO domain_event (id,type,schema_version,ts,household_id,correlation_id,"
            "origin,kind,payload_json,recorded_at)"
            " VALUES ('e','t',1,'x','h','c','real','measured','{}','x')"
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="imutável"):
        db.run_sync(lambda c: c.execute("UPDATE domain_event SET type='y'"))
    with pytest.raises(sqlite3.IntegrityError, match="imutável"):
        db.run_sync(lambda c: c.execute("DELETE FROM domain_event"))


# --- lifespan -------------------------------------------------------------------------------


def _app_with_probe(seen: list):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def feature_lifespan(app):
        # um lifespan de feature já encontra a base de dados pronta e migrada
        seen.append(
            app.state.db.run_sync(
                lambda c: c.execute("SELECT count(*) FROM schema_migration").fetchone()[0]
            )
        )
        yield
        seen.append("feature-stopped")

    app = FastAPI(lifespan=core_lifespan)
    app.include_router(APIRouter(lifespan=feature_lifespan))
    return app


def test_core_lifespan_starts_before_and_stops_after_features(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "l.sqlite3"))
    get_settings.cache_clear()
    seen: list = []
    app = _app_with_probe(seen)
    with TestClient(app):
        db = app.state.db
        migrated = db.run_sync(
            lambda c: c.execute("SELECT count(*) FROM schema_migration").fetchone()[0]
        )
        assert seen == [migrated]
    assert seen == [migrated, "feature-stopped"]
    with pytest.raises(DatabaseClosedError):  # fechou no shutdown
        db.run_sync(lambda c: None)
    get_settings.cache_clear()


def test_failed_startup_runs_no_feature_and_closes_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "f.sqlite3"))
    get_settings.cache_clear()
    monkeypatch.setattr(
        "homemind.core.lifespan.migrate", lambda db: (_ for _ in ()).throw(MigrationError("x"))
    )
    seen: list = []
    app = _app_with_probe(seen)
    with pytest.raises(MigrationError), TestClient(app):
        pass
    assert seen == []
    get_settings.cache_clear()


def test_real_app_exposes_shared_db():
    from homemind.main import app

    with TestClient(app):
        assert app.state.db.run_sync(lambda c: c.execute("SELECT 1").fetchone()[0]) == 1
