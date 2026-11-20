"""Regra B = votação (D-32) na feature `notifications`: cenários do serviço, concorrência de votos
(sem votos perdidos nem duplicados, uma só decisão) e eventos `notification.responded` por voto.

A regra em si é do contrato (`confirmation_outcome`, testada em `tests/test_confirmation_votes.py`);
aqui prova-se que a persistência e os eventos a respeitam."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts.common import Origin
from homemind.contracts.household import MembershipRole
from homemind.contracts.notification import (
    AlreadyRespondedError,
    ConfirmationVerdict,
    InvalidTargetError,
    Notification,
    NotificationAction,
    NotificationExpiredError,
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    NotificationStatus,
    UnknownActionError,
)
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.service import (
    NotificationNotFoundError,
    NotificationService,
)
from homemind.features.notifications.sqlite import SqliteNotificationRepository
from homemind.features.notifications.tests._fakes import (
    ANA,
    BRUNO,
    HOUSE,
    LANDLORD,
    OUTSIDER,
    FakeDirectory,
    confirmation_request,
    make_service,
    prov,
    uid,
)

CARLA, DIOGO = uid("carla"), uid("diogo")
TENANTS = [ANA, BRUNO, CARLA, DIOGO]  # 4 elegíveis -> bastam 2 votos «de outra pessoa»


def _directory() -> FakeDirectory:
    roles = {(HOUSE, t): MembershipRole.tenant for t in TENANTS}
    roles[(HOUSE, LANDLORD)] = MembershipRole.landlord
    return FakeDirectory(roles)


def _setup(eligible=None):
    svc, repo, clock = make_service(directory=_directory())
    out = svc.on_confirmation_needed(
        confirmation_request(now=clock(), eligible=eligible or [LANDLORD, *TENANTS]),
        source_event_id=uid("evento-1"),
        household_id=HOUSE,
        correlation_id=uid("corr"),
        provenance=prov(),
    )
    assert out.notification is not None
    return svc, repo, clock, out.notification.id


def _vote(svc, nid, who, action, target=None):
    return svc.respond(
        nid,
        household_id=HOUSE,
        resident_id=who,
        action_id=action,
        target_resident_ids=[target] if target else None,
    )


def _outcome(out):
    (ev,) = out.events
    assert isinstance(ev, de.NotificationResponded)
    assert ev.data.outcome is not None
    return ev.data.outcome


# --- os quatro veredictos ----------------------------------------------------------------------


def test_um_e_minha_fecha_e_paga_quem_assumiu():
    svc, repo, _, nid = _setup()
    out = _vote(svc, nid, BRUNO, "mine")
    outcome = _outcome(out)
    assert (outcome.verdict, outcome.resident_ids) == (ConfirmationVerdict.self_claimed, [BRUNO])
    stored = repo.get(nid)
    assert stored is not None and stored.status is NotificationStatus.actioned
    assert stored.response is not None and stored.response.resident_id == BRUNO
    assert len(stored.responses) == 1


def test_metade_arredondada_para_cima_atribui_a_outra_pessoa():
    svc, repo, _, nid = _setup()
    first = _vote(svc, nid, ANA, "other", DIOGO)
    assert _outcome(first).verdict is ConfirmationVerdict.pending
    assert first.notification is not None
    assert first.notification.status is NotificationStatus.unread  # 1 de 2: ainda aberta
    second = _vote(svc, nid, BRUNO, "other", DIOGO)
    outcome = _outcome(second)
    assert (outcome.verdict, outcome.resident_ids) == (
        ConfirmationVerdict.accusation_accepted,
        [DIOGO],
    )
    assert (outcome.votes, outcome.votes_needed) == (2, 2)
    stored = repo.get(nid)
    assert stored is not None and stored.status is NotificationStatus.actioned
    assert stored.response is not None and stored.response.resident_id == BRUNO  # o voto decisivo
    assert [r.resident_id for r in stored.responses] == [ANA, BRUNO]


def test_acusacoes_a_pessoas_diferentes_nao_fecham():
    svc, _, _, nid = _setup()
    _vote(svc, nid, ANA, "other", DIOGO)
    out = _vote(svc, nid, BRUNO, "other", CARLA)
    assert _outcome(out).verdict is ConfirmationVerdict.pending


def test_o_acusado_assume_antes_de_se_chegar_a_metade():
    svc, repo, _, nid = _setup()
    _vote(svc, nid, ANA, "other", DIOGO)
    out = _vote(svc, nid, DIOGO, "mine")
    outcome = _outcome(out)
    assert (outcome.verdict, outcome.resident_ids) == (ConfirmationVerdict.self_claimed, [DIOGO])
    stored = repo.get(nid)
    assert stored is not None and stored.status is NotificationStatus.actioned


def test_todos_votaram_sem_decisao_divide_se_por_todos():
    svc, repo, _, nid = _setup()
    _vote(svc, nid, ANA, "unknown")
    _vote(svc, nid, BRUNO, "everyone")
    _vote(svc, nid, CARLA, "other", DIOGO)
    out = _vote(svc, nid, DIOGO, "other", ANA)  # 1 voto em cada alvo: nenhum chega a 2
    outcome = _outcome(out)
    assert (outcome.verdict, outcome.resident_ids) == (ConfirmationVerdict.everyone, [])
    stored = repo.get(nid)
    assert stored is not None and stored.status is NotificationStatus.actioned
    assert len(stored.responses) == 4


def test_passadas_24h_sem_decisao_divide_se_por_todos_sem_aceitar_mais_votos():
    svc, repo, clock, nid = _setup()
    _vote(svc, nid, ANA, "unknown")
    clock.advance(hours=24)
    with pytest.raises(NotificationExpiredError):
        _vote(svc, nid, BRUNO, "mine")
    (view,) = svc.list_for(HOUSE, BRUNO)
    assert view.status is NotificationStatus.expired and view.can_respond is False
    assert view.voting is not None and view.voting.verdict is ConfirmationVerdict.everyone
    (expired,) = svc.expire_due()  # o varrimento mantém os votos e o veredicto
    assert expired.id == nid and len(expired.responses) == 1
    (view,) = svc.list_for(HOUSE, BRUNO)
    assert view.voting is not None and view.voting.verdict is ConfirmationVerdict.everyone
    stored = repo.get(nid)
    assert stored is not None and len(stored.responses) == 1


# --- um voto por pessoa e alvos inválidos ------------------------------------------------------


def test_um_voto_por_pessoa_e_o_segundo_e_409_sem_evento():
    svc, repo, _, nid = _setup()
    _vote(svc, nid, ANA, "unknown")
    for again in ("mine", "unknown"):
        with pytest.raises(AlreadyRespondedError):
            _vote(svc, nid, ANA, again)
    stored = repo.get(nid)
    assert stored is not None and [r.action_id for r in stored.responses] == ["unknown"]
    assert stored.status is NotificationStatus.unread


def test_votar_numa_votacao_fechada_e_409():
    svc, _, _, nid = _setup()
    _vote(svc, nid, ANA, "mine")
    with pytest.raises(AlreadyRespondedError):
        _vote(svc, nid, BRUNO, "mine")


@pytest.mark.parametrize(
    ("action", "target"),
    [
        ("other", None),  # `other` sem alvo
        ("mine", DIOGO),  # alvo com outra ação
        ("other", ANA),  # a si próprio (quem vota é a Ana)
        ("other", LANDLORD),  # o senhorio nunca é alvo
        ("other", OUTSIDER),  # nem quem não mora na casa
        ("other", uid("ninguem")),
    ],
)
def test_alvo_invalido_nao_consome_o_voto(action, target):
    svc, repo, _, nid = _setup()
    with pytest.raises(InvalidTargetError) as exc:
        _vote(svc, nid, ANA, action, target)
    assert exc.value.code == "invalid_request"
    stored = repo.get(nid)
    assert stored is not None and stored.responses == []
    assert _outcome(_vote(svc, nid, ANA, "unknown")).verdict is ConfirmationVerdict.pending


def test_senhorio_continua_sem_ver_nem_votar():
    svc, _, _, nid = _setup()
    with pytest.raises(NotificationNotFoundError):
        _vote(svc, nid, LANDLORD, "mine")
    assert svc.list_for(HOUSE, LANDLORD) == []


def test_outros_tipos_mantem_a_primeira_resposta_a_vencer():
    svc, repo, clock = make_service(directory=_directory())
    n = Notification(
        id=uid("agente"),
        household_id=HOUSE,
        scope=NotificationScope.household,
        responder_ids=[ANA, BRUNO],
        kind=NotificationKind.agent_action,
        severity=NotificationSeverity.info,
        title="Ação",
        body="Desligo o aquecedor?",
        origin=Origin.real,
        actions=[
            NotificationAction(id="yes", label="Sim"),
            NotificationAction(id="no", label="Não"),
        ],
        correlation_id=uid("corr"),
        created_at=clock.now,
    )
    repo.insert(n)
    out = svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="yes")
    (ev,) = out.events
    assert isinstance(ev, de.NotificationResponded) and ev.data.outcome is None
    with pytest.raises(AlreadyRespondedError):
        svc.respond(n.id, household_id=HOUSE, resident_id=BRUNO, action_id="no")
    # sem votação: `other` nem sequer é uma ação desta notificação
    n2 = n.model_copy(update={"id": uid("agente-2")})
    repo.insert(n2)
    with pytest.raises(UnknownActionError):
        svc.respond(n2.id, household_id=HOUSE, resident_id=ANA, action_id="other")


# --- eventos: um por voto ----------------------------------------------------------------------


def test_um_evento_por_voto_com_id_proprio_e_o_outcome():
    svc, _, _, nid = _setup()
    outs = [
        _vote(svc, nid, ANA, "other", DIOGO),
        _vote(svc, nid, BRUNO, "unknown"),
        _vote(svc, nid, CARLA, "other", DIOGO),
    ]
    events = [o.events[0] for o in outs]
    assert len({e.id for e in events}) == 3  # ids distintos (um por voto)
    assert [e.data.outcome.verdict for e in events] == [
        ConfirmationVerdict.pending,
        ConfirmationVerdict.pending,
        ConfirmationVerdict.accusation_accepted,
    ]
    assert [e.data.outcome.votes for e in events] == [1, 2, 3]
    assert [e.data.response.resident_id for e in events] == [ANA, BRUNO, CARLA]
    assert all(e.data.ref is not None for e in events)
    assert sum(e.data.outcome.decided for e in events) == 1  # só o último decide


# --- vista: anonimato --------------------------------------------------------------------------


def test_vista_nunca_revela_quem_votou():
    svc, _, _, nid = _setup()
    _vote(svc, nid, ANA, "other", DIOGO)
    _vote(svc, nid, BRUNO, "unknown")
    for viewer in (CARLA, DIOGO, BRUNO):
        (view,) = svc.list_for(HOUSE, viewer)
        text = view.model_dump_json()
        assert str(ANA) not in text, viewer  # Ana votou e não é alvo: nunca aparece
        assert view.voting is not None
        assert (
            view.voting.votes == 2 and view.voting.eligible == 4 and view.voting.votes_needed == 2
        )
        assert [(a.target_resident_ids, a.votes) for a in view.voting.accusations] == [([DIOGO], 1)]
    (carla,) = svc.list_for(HOUSE, CARLA)
    assert carla.voting is not None and carla.voting.my_vote is None and carla.can_respond is True
    (ana,) = svc.list_for(HOUSE, ANA)
    assert ana.voting is not None and ana.voting.my_vote is not None
    assert ana.voting.my_vote.by_me is True and ana.can_respond is False


# --- concorrência ------------------------------------------------------------------------------


def test_o_cas_perdido_rele_e_reaplica_sem_perder_o_voto_do_outro():
    """Entre a leitura e o CAS da Ana grava-se o voto do Bruno: o CAS da Ana falha, ela relê e o
    voto dela entra a seguir ao dele (ambos ficam; um só evento por voto)."""
    svc, repo, _, nid = _setup()
    original = repo.compare_and_set
    calls = {"n": 0}

    def intruded(new, *, expected):
        calls["n"] += 1
        if calls["n"] == 1:  # o Bruno vota entre a leitura e o CAS da Ana
            stored = repo.get(nid)
            assert stored is not None
            assert original(stored.respond(BRUNO, "unknown", svc._clock()), expected=stored)
        return original(new, expected=expected)

    repo.compare_and_set = intruded  # type: ignore[method-assign]
    out = _vote(svc, nid, ANA, "unknown")
    assert calls["n"] == 2  # o 1.º CAS da Ana perdeu; o 2.º (depois de reler) ganhou
    stored = repo.get(nid)
    assert stored is not None
    assert [r.resident_id for r in stored.responses] == [BRUNO, ANA]
    assert _outcome(out).votes == 2


def test_o_cas_perdido_para_um_voto_que_fecha_da_409():
    """Se o voto concorrente fecha a votação, o perdedor relê e recebe 409 (não sobrescreve)."""
    svc, repo, _, nid = _setup()
    original = repo.compare_and_set
    calls = {"n": 0}

    def intruded(new, *, expected):
        calls["n"] += 1
        if calls["n"] == 1:
            stored = repo.get(nid)
            assert stored is not None
            assert original(stored.respond(BRUNO, "mine", svc._clock()), expected=stored)
        return original(new, expected=expected)

    repo.compare_and_set = intruded  # type: ignore[method-assign]
    with pytest.raises(AlreadyRespondedError):
        _vote(svc, nid, ANA, "unknown")
    stored = repo.get(nid)
    assert stored is not None and [r.resident_id for r in stored.responses] == [BRUNO]


def _race(svc, nid, attempts):
    """Cada tentativa é (residente, ação, alvo); todas arrancam ao mesmo tempo."""
    barrier = threading.Barrier(len(attempts))

    def run(attempt):
        who, action, target = attempt
        barrier.wait()
        try:
            return _vote(svc, nid, who, action, target)
        except AlreadyRespondedError as e:
            return e

    with ThreadPoolExecutor(max_workers=len(attempts)) as pool:
        results = list(pool.map(run, attempts))
    return [r for r in results if not isinstance(r, AlreadyRespondedError)], [
        r for r in results if isinstance(r, AlreadyRespondedError)
    ]


@pytest.mark.parametrize("round_", range(5))
def test_votos_simultaneos_nao_se_perdem_nem_duplicam(round_):
    svc, repo, _, nid = _setup()
    attempts = [(t, "unknown", None) for t in TENANTS] * 2  # cada um tenta duas vezes
    accepted, rejected = _race(svc, nid, attempts)
    assert len(accepted) == 4 and len(rejected) == 4  # um voto por pessoa
    stored = repo.get(nid)
    assert stored is not None
    assert sorted(r.resident_id for r in stored.responses) == sorted(TENANTS)
    events = [o.events[0] for o in accepted]
    assert len({e.id for e in events}) == 4
    decided = [e for e in events if e.data.outcome.decided]
    assert len(decided) == 1  # exatamente uma decisão (a do último voto)
    assert decided[0].data.outcome.verdict is ConfirmationVerdict.everyone
    assert stored.status is NotificationStatus.actioned


@pytest.mark.parametrize("round_", range(5))
def test_e_minha_simultaneos_so_um_decide(round_):
    svc, repo, _, nid = _setup()
    accepted, rejected = _race(svc, nid, [(t, "mine", None) for t in TENANTS])
    assert len(accepted) == 1 and len(rejected) == 3
    assert _outcome(accepted[0]).decided
    stored = repo.get(nid)
    assert stored is not None and len(stored.responses) == 1
    assert stored.response is not None
    assert stored.response.resident_id == accepted[0].events[0].data.response.resident_id


def test_votos_simultaneos_em_sqlite_so_uma_decisao(db):
    """Mesma prova sobre SQLite real (CAS em `json_array_length`), uma transação por voto."""

    def seed(conn):
        for t, name in ((CARLA, "Carla"), (DIOGO, "Diogo")):
            conn.execute(
                "INSERT INTO resident (id, display_name, created_at) VALUES (?, ?, ?)",
                (str(t), name, "2026-11-17T12:00:00+00:00"),
            )
        for i, t in enumerate(TENANTS):
            conn.execute(
                "INSERT INTO room (id, household_id, name, kind) VALUES (?, ?, ?, 'bedroom')",
                (f"r{i}", str(HOUSE), f"r{i}"),
            )
            conn.execute(
                "INSERT INTO membership (id, household_id, resident_id, role, room_id, starts_on,"
                " status) VALUES (?, ?, ?, 'tenant', ?, '2026-09-01', 'active')",
                (f"m{i}", str(HOUSE), str(t), f"r{i}"),
            )

    db.run_sync(seed)
    now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    def service(conn):
        return NotificationService(
            SqliteNotificationRepository(conn), SqliteResidentDirectory(conn), lambda: now
        )

    created = db.run_sync(
        lambda c: service(c).on_confirmation_needed(
            confirmation_request(now=now, eligible=TENANTS),
            source_event_id=uid("evento-1"),
            household_id=HOUSE,
            correlation_id=uid("corr"),
            provenance=prov(),
        )
    )
    assert created.notification is not None
    nid = created.notification.id
    barrier = threading.Barrier(8)

    def attempt(who):
        barrier.wait()
        try:
            return db.run_sync(
                lambda c: service(c).respond(
                    nid, household_id=HOUSE, resident_id=who, action_id="unknown"
                )
            )
        except AlreadyRespondedError as e:
            return e

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, TENANTS * 2))
    accepted = [r for r in results if not isinstance(r, AlreadyRespondedError)]
    assert len(accepted) == 4
    stored = db.run_sync(lambda c: SqliteNotificationRepository(c).get(nid))
    assert stored is not None and len(stored.responses) == 4
    assert sorted(r.resident_id for r in stored.responses) == sorted(TENANTS)
    assert stored.status is NotificationStatus.actioned
    assert sum(r.events[0].data.outcome.decided for r in accepted) == 1


def test_expira_entre_a_leitura_e_o_cas_da_erro_de_expiracao():
    svc, repo, clock, nid = _setup()
    original = repo.compare_and_set
    done = False

    def sweep_first(new, *, expected):
        nonlocal done
        if not done:
            done = True
            clock.advance(hours=25)
            svc.expire_due()
        return original(new, expected=expected)

    repo.compare_and_set = sweep_first  # type: ignore[method-assign]
    with pytest.raises(NotificationExpiredError):
        _vote(svc, nid, ANA, "mine")
