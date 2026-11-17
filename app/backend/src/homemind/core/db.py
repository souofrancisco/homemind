"""SQLite partilhado: uma ligação, um lock, transações explícitas.

Um único processo FastAPI escreve; WAL e `busy_timeout` protegem ainda leituras externas
(ex.: `sqlite3` na linha de comandos). Todo o acesso passa por `transaction()` (síncrono, ex.:
visão numa thread) ou `await run(fn)` (corre `fn(conn)` numa thread, sem bloquear o event loop).
"""

import asyncio
import hashlib
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")


class DatabaseClosedError(RuntimeError):
    pass


class MigrationError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path | str, busy_timeout_ms: int = 5000) -> None:
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: BEGIN/COMMIT são nossos (nada de transações implícitas).
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        self._conn = conn

    def close(self) -> None:
        with self._lock:  # espera por uma transação em curso
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT; ROLLBACK se o bloco levantar."""
        with self._lock:
            conn = self._conn
            if conn is None:
                raise DatabaseClosedError("base de dados fechada")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def run_sync(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        with self.transaction() as conn:
            return fn(conn)

    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self.run_sync, fn)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def migrate(db: Database) -> list[str]:
    """Aplica, por ordem de nome, as migrações `core/migrations/NNNN_modulo_desc.sql` em falta.

    Cada ficheiro corre numa transação própria com o registo em `schema_migration`. Aplicadas
    por nome (não por «última versão»): dois ramos que acrescentem `0030_energy_x.sql` e
    `0040_billing_y.sql` não colidem. Um ficheiro já aplicado e depois alterado é erro
    (checksum). Idempotente; nunca apaga dados.
    """
    applied: list[str] = []
    with db._lock:
        conn = db._conn
        if conn is None:
            raise DatabaseClosedError("base de dados fechada")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migration ("
            "name TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        done = {r["name"]: r["checksum"] for r in conn.execute("SELECT * FROM schema_migration")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if not _MIGRATION_NAME.match(path.name):
                raise MigrationError(f"nome de migração inválido: {path.name}")
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if path.name in done:
                if done[path.name] != checksum:
                    raise MigrationError(f"migração já aplicada foi alterada: {path.name}")
                continue
            script = (
                f"BEGIN IMMEDIATE;\n{sql}\n"
                f"INSERT INTO schema_migration(name, checksum, applied_at) "
                f"VALUES ('{path.name}', '{checksum}', '{_now()}');\nCOMMIT;"
            )
            try:
                conn.executescript(script)
            except sqlite3.Error as e:
                if conn.in_transaction:  # executescript deixa a transação aberta se falhar a meio
                    conn.execute("ROLLBACK")
                raise MigrationError(f"migração {path.name} falhou ({type(e).__name__})") from e
            applied.append(path.name)
    return applied
