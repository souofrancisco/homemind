"""Operações locais e seguras da DEMO-01. Nunca lê DB_PATH nem usa MCP.

O caminho só é configurável por código para testes (DemoStore(tmp_path)); o CLI
usa sempre a pasta privada app/.demo-data, nunca uma base de desenvolvimento/produção.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from homemind.contracts import billing
from homemind.contracts import fixtures as fx
from homemind.core.db import Database, migrate
from homemind.core.events import append_event, load_events
from homemind.demo.scenario import events, references
from homemind.features.households.repo import seed_demo

DEMO_ROOT = Path(__file__).resolve().parents[4] / ".demo-data"
FILE_NAME = "conta-certa-demo.sqlite3"
MARKER = "conta-certa-DEMO-01-dedicated-v1"
SQLITE_MAGIC = b"SQLite format 3\x00"


class DemoSafetyError(RuntimeError):
    """Refusa operar quando o ficheiro não é exclusivamente da demonstração."""


@dataclass(frozen=True)
class DemoStore:
    root: Path

    @property
    def path(self) -> Path:
        return self.root / FILE_NAME

    def _guard(self, *, existing: bool) -> None:
        if self.root.is_symlink() or self.path.is_symlink():
            raise DemoSafetyError("symlink proibido para a base de demonstração")
        if self.root.exists() and not self.root.is_dir():
            raise DemoSafetyError("diretório de demo inválido")
        if not self.path.exists():
            if existing:
                raise DemoSafetyError("a base de demo não existe; executar demo-prepare")
            return
        info = self.path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DemoSafetyError("a base de demo não é um ficheiro independente")
        with self.path.open("rb") as source:
            if source.read(16) != SQLITE_MAGIC:
                raise DemoSafetyError("ficheiro existente não é uma base SQLite válida")
        # Evitar reset com outra ligação/processo potencialmente ativo.
        if any(Path(str(self.path) + suffix).exists() for suffix in ("-wal", "-shm")):
            raise DemoSafetyError("SQLite WAL/SHM presente; parar processos antes do reset")
        try:
            # immutable evita que a própria validação crie ficheiros -wal/-shm.
            with closing(
                sqlite3.connect(f"file:{self.path}?mode=ro&immutable=1", uri=True)
            ) as conn:
                conn.execute("PRAGMA query_only=ON")
                marker = conn.execute("SELECT token FROM demo_marker WHERE id=1").fetchone()
                houses = conn.execute("SELECT id, source_kind FROM household").fetchall()
                if marker != (MARKER,) or houses != [(str(fx.HOUSEHOLD), "demo")]:
                    raise DemoSafetyError("base não marcada como demo exclusiva")
        except sqlite3.Error as exc:
            raise DemoSafetyError("base sem marcador válido de demonstração") from exc

    @staticmethod
    def _populate(conn: sqlite3.Connection) -> None:
        if not seed_demo(conn):
            raise DemoSafetyError("a casa já existe na base nova")
        conn.execute("CREATE TABLE demo_marker (id INTEGER PRIMARY KEY, token TEXT NOT NULL)")
        conn.execute("INSERT INTO demo_marker VALUES (1, ?)", (MARKER,))
        conn.execute(
            "CREATE TABLE demo_reference (kind TEXT NOT NULL, id TEXT NOT NULL,"
            " payload_json TEXT NOT NULL, PRIMARY KEY(kind, id))"
        )
        for kind, identifier, model in references():
            conn.execute(
                "INSERT INTO demo_reference VALUES (?,?,?)",
                (kind, str(identifier), model.model_dump_json()),
            )
        for event in events():
            append_event(conn, event)

    def _build(self) -> None:
        self._guard(existing=False)
        self.root.mkdir(parents=True, exist_ok=True)
        # Só criamos/substituímos o ficheiro fixo. Um erro antes de replace deixa o antigo intacto.
        fd, tmp = tempfile.mkstemp(prefix=".demo-new-", suffix=".sqlite3", dir=self.root)
        os.close(fd)
        candidate = Path(tmp)
        try:
            db = Database(candidate)
            try:
                db.open()
                migrate(db)
                db.run_sync(self._populate)
            finally:
                db.close()
            os.replace(candidate, self.path)
        finally:
            candidate.unlink(missing_ok=True)

    def prepare(self) -> dict:
        if self.path.exists():
            self._guard(existing=True)
            self.replay()
        else:
            self._build()
        return self.verify()

    def reset(self) -> dict:
        if self.path.exists():
            self._guard(existing=True)
        self._build()
        return self.verify()

    def replay(self) -> dict:
        self._guard(existing=True)
        db = Database(self.path)
        try:
            db.open()

            def publish(conn: sqlite3.Connection) -> None:
                for event in events():
                    append_event(conn, event)  # F0 deduplica por id, conflito é erro

            db.run_sync(publish)
        finally:
            db.close()
        return self.verify()

    def verify(self) -> dict:
        self._guard(existing=True)
        db = Database(self.path)
        try:
            db.open()
            actual = db.run_sync(load_events)
            stored = [item.event for item in actual]
            expected = events()
            if stored != expected:
                raise AssertionError("o replay divergiu do cenário oficial")
            if [item.seq for item in actual] != list(range(1, len(expected) + 1)):
                raise AssertionError("ordem/duplicação de eventos inesperada")

            def check(conn: sqlite3.Connection) -> tuple[int, int, int]:
                return (
                    conn.execute("SELECT count(*) FROM membership WHERE role='tenant'").fetchone()[
                        0
                    ],
                    conn.execute("SELECT count(*) FROM demo_reference").fetchone()[0],
                    conn.execute("SELECT count(*) FROM household").fetchone()[0],
                )

            tenants, catalog, houses = db.run_sync(check)
            if (tenants, catalog, houses) != (4, len(references()), 1):
                raise AssertionError("seed/catálogo inesperado")
        finally:
            db.close()

        invoices = {}
        for label, factory in (("A", fx.bill_a), ("B", fx.bill_b)):
            bill, allocations = factory()
            billing.validate_allocations(bill, allocations)
            invoices[label] = [a.amount_cents for a in allocations]
            if sum(invoices[label]) != 12_000:
                raise AssertionError("a fatura de referência não fecha nos 120 €")
        if invoices["A"] == invoices["B"]:
            raise AssertionError("fixtures A e B confundidas")
        fingerprint = hashlib.sha256(
            "\n".join(event.model_dump_json() for event in expected).encode()
        ).hexdigest()
        return {
            "mode": "SIMULADO / offline",
            "source": "F0 + replay tipado (sem motores de negócio)",
            "households": houses,
            "tenants": tenants,
            "references": catalog,
            "events": len(stored),
            "event_digest": fingerprint,
            "reference_receipts_cents": invoices,
            "backend_ui_integrated": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Conta Certa — demo offline isolada")
    parser.add_argument("action", choices=("prepare", "reset", "replay", "verify"))
    parser.add_argument("--mode", choices=("offline", "hybrid"), default="offline")
    args = parser.parse_args()
    if args.mode != "offline":
        parser.error("híbrido bloqueado: sem fonte real validada nem adaptador aprovado")
    store = DemoStore(DEMO_ROOT)
    try:
        report = getattr(store, args.action)()
    except (DemoSafetyError, AssertionError, sqlite3.Error) as exc:
        parser.exit(2, f"DEMO RECUSADA: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
