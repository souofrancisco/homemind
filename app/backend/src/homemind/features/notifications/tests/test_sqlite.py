"""Persistência SQLite: o que o repositório em memória não pode provar (índices, CAS real,
recibos, preferências, ficheiro)."""

import sqlite3
import threading
from datetime import timedelta

import pytest

from homemind.contracts.common import Origin, replace
from homemind.contracts.notification import (
    NotificationKind,
    NotificationPreferences,
    NotificationStatus,
    QuietHours,
)
from homemind.core.db import Database, migrate
from homemind.features.notifications.compose import compose_confirmation
from homemind.features.notifications.sqlite import (
    SqliteNotificationRepository,
    load_preferences,
    save_preferences,
)
from homemind.features.notifications.tests._fakes import (
    ANA,
    BRUNO,
    HOUSE,
    OTHER_HOUSE,
    T0,
    confirmation_request,
    uid,
)
from homemind.features.notifications.tests.conftest import seed_fake_houses

OPEN = frozenset({NotificationStatus.unread, NotificationStatus.read})


def _n(source="e1", *, consumption="consumo-1", expires_in=timedelta(hours=24)):
    return compose_confirmation(
        confirmation_request(consumption=consumption, expires_in=expires_in),
        household_id=HOUSE,
        responder_ids=[ANA, BRUNO],
        origin=Origin.real,
        correlation_id=uid("corr"),
        source_event_id=uid(source),
        now=T0,
    )


def test_migracao_0300_aplica_do_zero_e_e_idempotente():
    db = Database(":memory:")
    db.open()
    try:
        applied = migrate(db)
        assert "0300_notifications_core.sql" in applied
        assert migrate(db) == []
        tables = {
            r["name"]
            for r in db.run_sync(lambda c: c.execute("SELECT name FROM sqlite_master").fetchall())
        }
        assert {"notification", "notification_read", "notification_preferences"} <= tables
    finally:
        db.close()


def test_cas_entre_threads_tem_um_so_vencedor(db):
    n = _n()
    db.run_sync(lambda c: SqliteNotificationRepository(c).insert(n))
    attempts = 8
    barrier = threading.Barrier(attempts)
    results: list[bool] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        won = db.run_sync(
            lambda c: SqliteNotificationRepository(c).compare_and_set(
                replace(n, status=NotificationStatus.expired), expected=n
            )
        )
        with lock:
            results.append(won)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and len(results) == attempts


def test_indice_de_deduplicacao_so_admite_um_pedido_aberto(db):
    first, second = _n("e1"), _n("e2")  # outro evento de origem, mesmo consumo
    assert first.id != second.id
    db.run_sync(lambda c: SqliteNotificationRepository(c).insert(first))
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: SqliteNotificationRepository(c).insert(second))
    # fechado o primeiro, o segundo já entra
    db.run_sync(
        lambda c: SqliteNotificationRepository(c).compare_and_set(
            replace(first, status=NotificationStatus.expired), expected=first
        )
    )
    assert db.run_sync(lambda c: SqliteNotificationRepository(c).insert(second)) is True


def test_indice_de_deduplicacao_so_vale_para_pedidos_de_confirmacao(db):
    # `kind` fora do índice: a coluna é livre (sem CHECK) e o mesmo `ref` repete-se
    def insert(conn):
        for source in ("e1", "e2"):
            n = _n(source)
            conn.execute(
                "INSERT INTO notification (id, household_id, scope, kind, status, ref_type,"
                " ref_id, created_at, origin, json, updated_at)"
                " VALUES (?,?,'household','info','unread','consumption_event','x',?,'real','{}',?)",
                (str(n.id), str(HOUSE), T0.isoformat(), T0.isoformat()),
            )

    db.run_sync(insert)  # não levanta


def test_recibo_repetido_nao_duplica_e_exige_notificacao_existente(db):
    n = _n()
    repo_call = lambda fn: db.run_sync(lambda c: fn(SqliteNotificationRepository(c)))  # noqa: E731
    repo_call(lambda r: r.insert(n))
    at = T0 + timedelta(minutes=1)
    assert repo_call(lambda r: r.mark_read(n.id, ANA, at)) is True
    assert repo_call(lambda r: r.mark_read(n.id, ANA, at + timedelta(minutes=9))) is False
    assert repo_call(lambda r: r.read_at(n.id, ANA)) == at
    assert repo_call(lambda r: r.read_at(n.id, BRUNO)) is None
    assert repo_call(lambda r: r.mark_read(uid("nao-existe"), ANA, at)) is False


def test_json_corrompido_nao_passa_a_validacao(db):
    n = _n()
    db.run_sync(lambda c: SqliteNotificationRepository(c).insert(n))
    db.run_sync(
        lambda c: c.execute("UPDATE notification SET json = '{}' WHERE id = ?", (str(n.id),))
    )
    with pytest.raises(ValueError):
        db.run_sync(lambda c: SqliteNotificationRepository(c).get(n.id))


def test_check_de_ambito_e_destinatario(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(
            lambda c: c.execute(
                "INSERT INTO notification (id, household_id, scope, kind, status, created_at,"
                " origin, json, updated_at) VALUES ('x', ?, 'personal', 'info', 'unread', 't',"
                " 'real', '{}', 't')",
                (str(HOUSE),),
            )
        )


def test_preferencias_ida_e_volta_e_atualizacao(db):
    assert db.run_sync(lambda c: load_preferences(c, ANA, HOUSE)) is None
    from datetime import time

    prefs = NotificationPreferences(
        resident_id=ANA,
        quiet_hours=QuietHours(start=time(22, 0), end=time(8, 0)),
        disabled_kinds=[NotificationKind.saving_tip],
    )
    db.run_sync(lambda c: save_preferences(c, HOUSE, prefs))
    assert db.run_sync(lambda c: load_preferences(c, ANA, HOUSE)) == prefs
    newer = NotificationPreferences(resident_id=ANA)
    db.run_sync(lambda c: save_preferences(c, HOUSE, newer))
    assert db.run_sync(lambda c: load_preferences(c, ANA, HOUSE)) == newer
    assert db.run_sync(lambda c: load_preferences(c, BRUNO, HOUSE)) is None


def test_preferencias_sao_por_residente_e_por_casa(db):
    from datetime import time

    night = NotificationPreferences(
        resident_id=ANA, quiet_hours=QuietHours(start=time(22, 0), end=time(8, 0))
    )
    db.run_sync(lambda c: save_preferences(c, HOUSE, night))
    assert db.run_sync(lambda c: load_preferences(c, ANA, OTHER_HOUSE)) is None
    other = NotificationPreferences(resident_id=ANA, disabled_kinds=[NotificationKind.peak_alert])
    db.run_sync(lambda c: save_preferences(c, OTHER_HOUSE, other))
    assert db.run_sync(lambda c: load_preferences(c, ANA, HOUSE)) == night
    assert db.run_sync(lambda c: load_preferences(c, ANA, OTHER_HOUSE)) == other
    rows = db.run_sync(
        lambda c: c.execute(
            "SELECT household_id FROM notification_preferences WHERE resident_id = ?",
            (str(ANA),),
        ).fetchall()
    )
    assert {r["household_id"] for r in rows} == {str(HOUSE), str(OTHER_HOUSE)}


def test_ficheiro_persiste_depois_de_reabrir(tmp_path):
    path = tmp_path / "notificacoes.sqlite3"
    n = _n()
    db = Database(path)
    db.open()
    migrate(db)
    db.run_sync(seed_fake_houses)
    db.run_sync(lambda c: SqliteNotificationRepository(c).insert(n))
    db.close()

    again = Database(path)
    again.open()
    try:
        assert migrate(again) == []
        assert again.run_sync(lambda c: SqliteNotificationRepository(c).get(n.id)) == n
    finally:
        again.close()


def test_resposta_concorrente_sobre_sqlite_tem_um_so_vencedor(db):
    """O serviço completo (visibilidade, contrato, CAS) sobre SQLite, a partir de várias threads."""
    from datetime import UTC, datetime

    from homemind.contracts.notification import AlreadyRespondedError
    from homemind.features.notifications.directory import SqliteResidentDirectory
    from homemind.features.notifications.service import NotificationService

    def seed_members(conn):
        for rid, role, room in ((ANA, "tenant", "r1"), (BRUNO, "tenant", "r2")):
            conn.execute(
                "INSERT INTO room (id, household_id, name, kind) VALUES (?, ?, ?, 'bedroom')",
                (room, str(HOUSE), room),
            )
            conn.execute(
                "INSERT INTO membership (id, household_id, resident_id, role, room_id, starts_on,"
                " status) VALUES (?, ?, ?, ?, ?, '2026-09-01', 'active')",
                (f"m-{room}", str(HOUSE), str(rid), role, room),
            )

    db.run_sync(seed_members)
    now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    n = _n()
    db.run_sync(lambda c: SqliteNotificationRepository(c).insert(n))
    attempts = 8
    barrier = threading.Barrier(attempts)
    outcomes: list[object] = []
    lock = threading.Lock()

    def attempt(resident) -> None:
        barrier.wait()

        def work(conn):
            service = NotificationService(
                SqliteNotificationRepository(conn), SqliteResidentDirectory(conn), lambda: now
            )
            return service.respond(n.id, household_id=HOUSE, resident_id=resident, action_id="mine")

        try:
            result: object = db.run_sync(work)
        except AlreadyRespondedError as e:
            result = e
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=attempt, args=([ANA, BRUNO][i % 2],)) for i in range(attempts)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    losers = [o for o in outcomes if isinstance(o, AlreadyRespondedError)]
    assert len(outcomes) == attempts and len(losers) == attempts - 1
