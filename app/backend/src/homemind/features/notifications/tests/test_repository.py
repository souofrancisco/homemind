import threading
from datetime import timedelta

import pytest

from homemind.contracts.common import Origin, replace
from homemind.contracts.notification import NotificationStatus
from homemind.features.notifications.compose import compose_confirmation
from homemind.features.notifications.repository import InMemoryNotificationRepository
from homemind.features.notifications.sqlite import SqliteNotificationRepository
from homemind.features.notifications.tests._fakes import (
    ANA,
    BRUNO,
    HOUSE,
    OTHER_HOUSE,
    T0,
    confirmation_request,
    uid,
)


class _SqlRepo:
    """O repositório SQLite como o serviço o usa, mas com uma transação por chamada (e o lock da
    base de dados), para correr os mesmos testes que a versão em memória, também entre threads."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        def call(*args, **kwargs):
            return self._db.run_sync(
                lambda conn: getattr(SqliteNotificationRepository(conn), name)(*args, **kwargs)
            )

        return call


@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    if request.param == "memory":
        return InMemoryNotificationRepository()
    return _SqlRepo(request.getfixturevalue("db"))


def _n(source="e1", *, consumption="consumo-1", house=HOUSE, expires_in=timedelta(hours=24)):
    return compose_confirmation(
        confirmation_request(consumption=consumption, expires_in=expires_in),
        household_id=house,
        responder_ids=[ANA, BRUNO],
        origin=Origin.real,
        correlation_id=uid("corr"),
        source_event_id=uid(source),
        now=T0,
    )


def test_insert_e_get(repo):
    n = _n()
    assert repo.get(n.id) is None
    assert repo.insert(n) is True
    assert repo.get(n.id) == n


def test_insert_repetido_devolve_false_e_nao_altera(repo):
    n = _n()
    repo.insert(n)
    assert repo.insert(replace(n, body="outro texto")) is False
    assert repo.get(n.id) == n


def test_find_open_por_chave(repo):
    n = _n()
    repo.insert(n)
    key = {
        "household_id": HOUSE,
        "kind": n.kind,
        "ref": n.ref,
        "recipient_resident_id": None,
    }
    assert repo.find_open(**key) == n
    assert repo.find_open(**(key | {"household_id": OTHER_HOUSE})) is None
    assert repo.find_open(**(key | {"recipient_resident_id": ANA})) is None
    repo.compare_and_set(replace(n, status=NotificationStatus.expired), expected=n)
    assert repo.find_open(**key) is None


def test_compare_and_set_so_com_estado_esperado(repo):
    n = _n()
    repo.insert(n)
    read = replace(n, status=NotificationStatus.read)
    assert repo.compare_and_set(read, expected=read) is False  # o estado lido era `unread`
    assert repo.compare_and_set(read, expected=n) is True
    expired = replace(n, status=NotificationStatus.expired)
    assert repo.compare_and_set(expired, expected=n) is False  # entretanto passou a `read`
    assert repo.compare_and_set(expired, expected=read) is True
    assert repo.compare_and_set(read, expected=read) is False  # já não está nesse estado
    assert repo.get(n.id).status is NotificationStatus.expired  # type: ignore[union-attr]


def test_compare_and_set_exige_o_n_de_votos_lido(repo):
    """Mesmo estado (`unread`) mas mais um voto gravado por outrem: quem leu antes perde, para
    que um voto nunca se perca nem se grave duas vezes."""
    n = _n()
    repo.insert(n)
    after_ana = n.respond(ANA, "everyone", T0)
    assert after_ana.status is NotificationStatus.unread and len(after_ana.responses) == 1
    after_bruno_stale = n.respond(BRUNO, "unknown", T0)  # lido antes do voto da Ana
    assert repo.compare_and_set(after_ana, expected=n) is True
    assert repo.compare_and_set(after_bruno_stale, expected=n) is False
    # Relido: já aplica, com os dois votos (o último fecha: todos votaram).
    current = repo.get(n.id)
    assert current is not None and len(current.responses) == 1
    final = current.respond(BRUNO, "unknown", T0)
    assert repo.compare_and_set(final, expected=current) is True
    stored = repo.get(n.id)
    assert stored is not None and len(stored.responses) == 2
    assert stored.status is NotificationStatus.actioned


def test_compare_and_set_de_inexistente_e_false(repo):
    n = _n()
    assert repo.compare_and_set(n, expected=n) is False


def test_cas_concorrente_so_um_ganha(repo):
    n = _n()
    repo.insert(n)
    threads_n = 8
    barrier = threading.Barrier(threads_n)
    results: list[bool] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        won = repo.compare_and_set(replace(n, status=NotificationStatus.expired), expected=n)
        with lock:
            results.append(won)

    threads = [threading.Thread(target=attempt) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert len(results) == threads_n


def test_list_household_isola_casas(repo):
    a, b = _n("e1"), _n("e2", house=OTHER_HOUSE)
    repo.insert(a)
    repo.insert(b)
    assert repo.list_household(HOUSE) == [a]
    assert repo.list_household(OTHER_HOUSE) == [b]


def test_open_due_so_abertas_vencidas(repo):
    due = _n("e1", consumption="c1", expires_in=timedelta(hours=1))
    later = _n("e2", consumption="c2", expires_in=timedelta(hours=5))
    done = _n("e3", consumption="c3", expires_in=timedelta(hours=1))
    for n in (due, later, done):
        repo.insert(n)
    repo.compare_and_set(replace(done, status=NotificationStatus.dismissed), expected=done)
    assert repo.open_due(T0 + timedelta(hours=1)) == [due]
    assert repo.open_due(T0) == []


def test_recibos_de_leitura_por_residente(repo):
    n = _n()
    repo.insert(n)
    at = T0 + timedelta(minutes=1)
    assert repo.read_at(n.id, ANA) is None
    assert repo.mark_read(n.id, ANA, at) is True
    assert repo.mark_read(n.id, ANA, at + timedelta(minutes=5)) is False
    assert repo.read_at(n.id, ANA) == at
    assert repo.read_at(n.id, BRUNO) is None
    assert repo.mark_read(uid("nao-existe"), ANA, at) is False
