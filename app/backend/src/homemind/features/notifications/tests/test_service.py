import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.notification import (
    AlreadyRespondedError,
    NotAllowedToRespondError,
    Notification,
    NotificationExpiredError,
    NotificationKind,
    NotificationPreferences,
    NotificationScope,
    NotificationSeverity,
    NotificationStatus,
    QuietHours,
    RefType,
    UnknownActionError,
)
from homemind.features.notifications.preferences import Delivery
from homemind.features.notifications.service import (
    NotificationNotFoundError,
    NotificationService,
)
from homemind.features.notifications.tests._fakes import (
    ANA,
    BRUNO,
    HOUSE,
    LANDLORD,
    OTHER_HOUSE,
    OUTSIDER,
    FakeClock,
    FakeDirectory,
    confirmation_request,
    make_service,
    prov,
    uid,
)


def _create(svc: NotificationService, source="evento-1", **req_kw):
    return svc.on_confirmation_needed(
        confirmation_request(now=svc._clock(), **req_kw),
        source_event_id=uid(source),
        household_id=HOUSE,
        correlation_id=uid("corr"),
        provenance=prov(),
    )


def _budget(svc: NotificationService, source="limiar-50", pct=50, resident=ANA, house=HOUSE):
    return svc.on_budget_threshold(
        source_event_id=uid(source),
        household_id=house,
        resident_id=resident,
        budget_id=uid("orcamento"),
        pct=pct,
        spent_cents=1000,
        limit_cents=2000,
        forecast_cents=None,
        correlation_id=uid("corr"),
        provenance=prov(),
    )


# --- criação -----------------------------------------------------------------------------------


def test_criacao_emite_um_evento_com_ids_deterministicos():
    svc, repo, _ = make_service()
    out = _create(svc)
    n = out.notification
    assert n is not None
    assert repo.get(n.id) == n
    assert len(out.events) == 1
    ev = out.events[0]
    assert isinstance(ev, de.NotificationCreated)
    assert ev.type == "notification.created"
    assert ev.household_id == HOUSE
    assert ev.correlation_id == uid("corr")
    assert ev.data.notification_id == n.id
    assert ev.data.scope is NotificationScope.household
    assert ev.data.kind is NotificationKind.confirmation_request
    assert ev.provenance == prov()  # a do evento de origem


def test_criacao_idempotente_sem_segundo_evento():
    svc, repo, _ = make_service()
    first = _create(svc)
    second = _create(svc)
    assert second.events == ()
    assert second.notification == first.notification
    assert len(repo.list_household(HOUSE)) == 1


def test_dedupe_pedido_aberto_para_o_mesmo_consumo():
    svc, repo, _ = make_service()
    first = _create(svc, "evento-1")
    again = _create(svc, "evento-2")  # outro evento de origem, mesmo consumo
    assert again.events == ()
    assert again.notification == first.notification
    assert len(repo.list_household(HOUSE)) == 1


def test_novo_pedido_depois_do_anterior_respondido():
    svc, repo, _ = make_service()
    first = _create(svc, "evento-1")
    svc.respond(first.notification.id, household_id=HOUSE, resident_id=ANA, action_id="mine")  # type: ignore[union-attr]
    again = _create(svc, "evento-2")
    assert len(again.events) == 1
    assert again.notification.id != first.notification.id  # type: ignore[union-attr]
    assert len(repo.list_household(HOUSE)) == 2


def test_novo_pedido_depois_do_anterior_expirar_por_tempo():
    svc, _, clock = make_service()
    first = _create(svc, "evento-1", expires_in=timedelta(hours=1))
    clock.advance(hours=2)  # ainda `unread` na base, mas já vencido
    again = _create(svc, "evento-2")
    assert len(again.events) == 1
    assert again.notification.id != first.notification.id  # type: ignore[union-attr]


def test_consumos_diferentes_nao_se_deduplicam():
    svc, repo, _ = make_service()
    _create(svc, "evento-1", consumption="consumo-1")
    out = _create(svc, "evento-2", consumption="consumo-2")
    assert len(out.events) == 1
    assert len(repo.list_household(HOUSE)) == 2


def test_senhorio_e_filtrado_dos_responsaveis():
    svc, _, _ = make_service()
    n = _create(svc, eligible=[LANDLORD, ANA]).notification
    assert n is not None
    assert n.responder_ids == [ANA]


def test_sem_inquilinos_elegiveis_nao_cria_nada():
    svc, repo, _ = make_service()
    out = _create(svc, eligible=[LANDLORD, OUTSIDER])
    assert out.notification is None
    assert out.events == ()
    assert repo.list_household(HOUSE) == []


def test_pedido_ja_caducado_nao_cria_nada():
    svc, repo, _ = make_service()
    out = svc.on_confirmation_needed(
        confirmation_request(expires_in=timedelta(hours=-1)),
        source_event_id=uid("evento-1"),
        household_id=HOUSE,
        correlation_id=uid("corr"),
        provenance=prov(),
    )
    assert out.notification is None
    assert repo.list_household(HOUSE) == []


def test_origem_simulada_propaga_se_a_notificacao_e_ao_evento():
    svc, _, _ = make_service()
    out = svc.on_confirmation_needed(
        confirmation_request(),
        source_event_id=uid("evento-1"),
        household_id=HOUSE,
        correlation_id=uid("corr"),
        provenance=prov(Origin.simulated),
    )
    assert out.notification.origin is Origin.simulated  # type: ignore[union-attr]
    assert "(SIMULADO)" in out.notification.body  # type: ignore[union-attr]
    assert out.events[0].provenance.simulated


def test_alerta_de_orcamento_pessoal_e_idempotente():
    svc, repo, _ = make_service()
    out = _budget(svc)
    assert out.notification is not None
    assert out.notification.recipient_resident_id == ANA
    assert [e.type for e in out.events] == ["notification.created"]
    again = _budget(svc)
    assert again.events == ()
    assert again.notification == out.notification
    assert len(repo.list_household(HOUSE)) == 1


def test_limiares_do_mesmo_orcamento_geram_avisos_distintos():
    svc, repo, _ = make_service()
    _budget(svc, "limiar-50", pct=50)
    out = _budget(svc, "limiar-80", pct=80)
    assert len(out.events) == 1
    assert len(repo.list_household(HOUSE)) == 2


def test_alerta_de_orcamento_de_nao_membro_e_ignorado():
    svc, repo, _ = make_service()
    assert _budget(svc, resident=OUTSIDER).notification is None
    assert repo.list_household(HOUSE) == []


# --- resposta ----------------------------------------------------------------------------------


def test_resposta_feliz_emite_um_evento_com_ref():
    svc, repo, clock = make_service()
    n = _create(svc).notification
    assert n is not None
    clock.advance(minutes=5)
    out = svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")
    assert out.notification is not None
    assert out.notification.status is NotificationStatus.actioned
    assert repo.get(n.id).status is NotificationStatus.actioned  # type: ignore[union-attr]
    assert len(out.events) == 1
    ev = out.events[0]
    assert isinstance(ev, de.NotificationResponded)
    assert ev.type == "notification.responded"
    assert ev.data.response.resident_id == ANA
    assert ev.data.response.action_id == "mine"
    assert ev.data.response.responded_at == clock.now
    assert ev.data.ref is not None
    assert (ev.data.ref.type, ev.data.ref.id) == (RefType.consumption_event, uid("consumo-1"))
    assert ev.provenance.origin is Origin.real
    assert ev.provenance.kind is ValueKind.measured
    assert ev.household_id == HOUSE


def test_segunda_resposta_e_409_sem_evento_e_nao_altera_a_primeira():
    svc, repo, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")
    with pytest.raises(AlreadyRespondedError) as exc:
        svc.respond(n.id, household_id=HOUSE, resident_id=BRUNO, action_id="everyone")
    assert exc.value.code == "already_responded"
    stored = repo.get(n.id)
    assert stored is not None and stored.response is not None
    assert stored.response.resident_id == ANA


def test_mesmo_residente_a_repetir_tambem_e_409():
    svc, _, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")
    with pytest.raises(AlreadyRespondedError):
        svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")


def test_senhorio_nao_ve_nem_responde_a_confirmacoes():
    svc, _, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    with pytest.raises(NotificationNotFoundError) as exc:
        svc.respond(n.id, household_id=HOUSE, resident_id=LANDLORD, action_id="mine")
    assert exc.value.code == "notification_not_found"


def test_inexistente_e_nao_visivel_sao_indistinguiveis():
    svc, _, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    for rid in (OUTSIDER, uid("desconhecido")):
        with pytest.raises(NotificationNotFoundError):
            svc.respond(n.id, household_id=HOUSE, resident_id=rid, action_id="mine")
    with pytest.raises(NotificationNotFoundError):
        svc.respond(uid("nao-existe"), household_id=HOUSE, resident_id=ANA, action_id="mine")


def test_nao_destinatario_de_notificacao_pessoal_nao_a_ve():
    svc, _, _ = make_service()
    n = _budget(svc).notification
    assert n is not None
    with pytest.raises(NotificationNotFoundError):
        svc.respond(n.id, household_id=HOUSE, resident_id=BRUNO, action_id="mine")


def test_acao_desconhecida_nao_consome_a_notificacao():
    svc, repo, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    with pytest.raises(UnknownActionError):
        svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="desliga")
    assert repo.get(n.id).status is NotificationStatus.unread  # type: ignore[union-attr]
    assert len(svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine").events) == 1


def test_morador_que_nao_estava_nos_responsaveis_nao_responde():
    directory = FakeDirectory()
    svc, _, _ = make_service(directory=directory)
    n = _create(svc, eligible=[ANA]).notification
    assert n is not None
    with pytest.raises(NotAllowedToRespondError):
        svc.respond(n.id, household_id=HOUSE, resident_id=BRUNO, action_id="mine")


def test_resposta_a_pedido_expirado_por_tempo_e_a_notificacao_expirada():
    svc, _, clock = make_service()
    n = _create(svc, expires_in=timedelta(hours=1)).notification
    assert n is not None
    clock.advance(hours=1)
    with pytest.raises(NotificationExpiredError):
        svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")
    svc.expire_due()
    with pytest.raises(NotificationExpiredError):
        svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")


def test_resposta_concorrente_tem_um_so_vencedor_e_um_evento():
    svc, repo, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    attempts = 8
    barrier = threading.Barrier(attempts)
    residents = [ANA, BRUNO] * (attempts // 2)

    def attempt(resident):
        barrier.wait()
        try:
            return svc.respond(n.id, household_id=HOUSE, resident_id=resident, action_id="mine")
        except AlreadyRespondedError as e:
            return e

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(attempt, residents))
    winners = [r for r in results if not isinstance(r, AlreadyRespondedError)]
    assert len(winners) == 1
    assert len(winners[0].events) == 1
    assert sum(isinstance(r, AlreadyRespondedError) for r in results) == attempts - 1
    stored = repo.get(n.id)
    assert stored is not None and stored.response is not None
    assert stored.response.resident_id == winners[0].events[0].data.response.resident_id


def test_a_corrida_perdida_para_o_varrimento_e_expirada():
    """Se a notificação expira entre a leitura e o CAS, o erro é de expiração (não 409)."""
    svc, repo, clock = make_service()
    n = _create(svc, expires_in=timedelta(hours=1)).notification
    assert n is not None
    original_cas = repo.compare_and_set

    first_call = True

    def cas_apos_varrimento(new, *, expected):
        nonlocal first_call
        if first_call:  # o varrimento corre entre a leitura e o CAS da resposta
            first_call = False
            clock.advance(hours=2)
            svc.expire_due()
        return original_cas(new, expected=expected)

    repo.compare_and_set = cas_apos_varrimento  # type: ignore[method-assign]
    with pytest.raises(NotificationExpiredError):
        svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine")


# --- isolamento e visibilidade -----------------------------------------------------------------


def test_isolamento_entre_casas():
    svc, _, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    assert svc.list_for(OTHER_HOUSE, OUTSIDER) == []
    # um residente de outra casa a pedir a lista desta casa também não vê nada
    assert svc.list_for(HOUSE, OUTSIDER) == []
    with pytest.raises(NotificationNotFoundError):
        svc.mark_read(n.id, household_id=HOUSE, resident_id=OUTSIDER)


def test_visibilidade_pessoal_so_o_destinatario():
    svc, _, _ = make_service()
    _budget(svc)
    assert len(svc.list_for(HOUSE, ANA)) == 1
    assert svc.list_for(HOUSE, BRUNO) == []
    assert svc.list_for(HOUSE, LANDLORD) == []


def test_visibilidade_household_todos_os_inquilinos_e_senhorio_nunca_ve_confirmacoes():
    svc, _, _ = make_service()
    _create(svc)
    assert len(svc.list_for(HOUSE, ANA)) == 1
    assert len(svc.list_for(HOUSE, BRUNO)) == 1
    assert svc.list_for(HOUSE, LANDLORD) == []


def test_senhorio_nao_ve_alertas_de_seguranca_da_casa():
    svc, repo, clock = make_service()
    repo.insert(
        Notification(
            id=uid("seguranca"),
            household_id=HOUSE,
            scope=NotificationScope.household,
            kind=NotificationKind.security_alert,
            severity=NotificationSeverity.critical,
            title="Entrada com a casa vazia",
            body="Houve uma entrada com a casa vazia.",
            origin=Origin.real,
            correlation_id=uid("corr"),
            created_at=clock.now,
        )
    )
    assert svc.list_for(HOUSE, LANDLORD) == []  # derivado de presença: só inquilinos
    assert len(svc.list_for(HOUSE, ANA)) == 1


@pytest.mark.parametrize("scope", ["household", "personal"])
@pytest.mark.parametrize("kind", list(NotificationKind))
def test_senhorio_so_ve_os_tipos_da_allow_list(kind, scope):
    """Allow-list: o senhorio só vê `info`, na casa ou endereçada a ele (pessoal); o inquilino
    destinatário vê sempre."""
    svc, repo, clock = make_service()
    personal = scope == "personal"
    repo.insert(
        Notification(
            id=uid(f"allow-{kind}-{scope}"),
            household_id=HOUSE,
            scope=NotificationScope.personal if personal else NotificationScope.household,
            recipient_resident_id=LANDLORD if personal else None,
            kind=kind,
            severity=NotificationSeverity.info,
            title="Aviso",
            body="Texto.",
            origin=Origin.real,
            expires_at=clock.now + timedelta(hours=1)
            if kind is NotificationKind.confirmation_request
            else None,
            correlation_id=uid("corr"),
            created_at=clock.now,
        )
    )
    seen = svc.list_for(HOUSE, LANDLORD)
    assert (len(seen) == 1) is (kind is NotificationKind.info), (kind, scope)
    if not personal:
        assert len(svc.list_for(HOUSE, ANA)) == 1  # o inquilino vê todos os da casa
    if kind is not NotificationKind.info:
        with pytest.raises(NotificationNotFoundError):
            svc.mark_read(uid(f"allow-{kind}-{scope}"), household_id=HOUSE, resident_id=LANDLORD)


def test_filtros_limit_e_ordem():
    svc, _, clock = make_service()
    _create(svc, "evento-1", consumption="consumo-1")
    clock.advance(minutes=1)
    _budget(svc, "limiar-50", pct=50)
    clock.advance(minutes=1)
    _create(svc, "evento-2", consumption="consumo-2")
    views = svc.list_for(HOUSE, ANA)
    assert [v.kind for v in views] == [
        NotificationKind.confirmation_request,
        NotificationKind.budget_alert,
        NotificationKind.confirmation_request,
    ]
    assert [v.created_at for v in views] == sorted((v.created_at for v in views), reverse=True)
    assert len(svc.list_for(HOUSE, ANA, limit=2)) == 2
    assert svc.list_for(HOUSE, ANA, limit=1)[0].id == views[0].id
    personal = svc.list_for(HOUSE, ANA, scope=NotificationScope.personal)
    assert [v.kind for v in personal] == [NotificationKind.budget_alert]
    assert len(svc.list_for(HOUSE, ANA, status=NotificationStatus.read)) == 0
    assert len(svc.list_for(HOUSE, ANA, status=NotificationStatus.unread)) == 3
    with pytest.raises(ValueError):
        svc.list_for(HOUSE, ANA, limit=0)


def test_view_can_respond_e_by_me():
    svc, _, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    (view,) = svc.list_for(HOUSE, ANA)
    assert view.can_respond is True
    assert view.response is None
    svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="everyone")
    (mine,) = svc.list_for(HOUSE, ANA)
    (theirs,) = svc.list_for(HOUSE, BRUNO)
    assert mine.status is NotificationStatus.actioned
    assert mine.can_respond is False
    assert mine.response is not None and mine.response.by_me is True
    assert theirs.response is not None and theirs.response.by_me is False
    assert theirs.response.action_id == "everyone"
    assert "resident" not in theirs.model_dump_json()


# --- leitura -----------------------------------------------------------------------------------


def test_mark_read_em_household_e_por_residente():
    svc, repo, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    view = svc.mark_read(n.id, household_id=HOUSE, resident_id=ANA)
    assert view.status is NotificationStatus.read
    assert repo.get(n.id).status is NotificationStatus.unread  # type: ignore[union-attr]
    (ana,) = svc.list_for(HOUSE, ANA)
    (bruno,) = svc.list_for(HOUSE, BRUNO)
    assert ana.status is NotificationStatus.read
    assert bruno.status is NotificationStatus.unread
    assert len(svc.list_for(HOUSE, ANA, status=NotificationStatus.read)) == 1
    assert len(svc.list_for(HOUSE, BRUNO, status=NotificationStatus.read)) == 0


def test_mark_read_em_pessoal_muda_o_estado_partilhado():
    svc, repo, _ = make_service()
    n = _budget(svc).notification
    assert n is not None
    assert (
        svc.mark_read(n.id, household_id=HOUSE, resident_id=ANA).status is NotificationStatus.read
    )
    assert repo.get(n.id).status is NotificationStatus.read  # type: ignore[union-attr]
    assert (
        svc.mark_read(n.id, household_id=HOUSE, resident_id=ANA).status is NotificationStatus.read
    )  # idempotente


def test_ler_nao_impede_responder_e_responder_depois_de_lida_funciona():
    svc, _, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    svc.mark_read(n.id, household_id=HOUSE, resident_id=ANA)
    assert len(svc.respond(n.id, household_id=HOUSE, resident_id=ANA, action_id="mine").events) == 1


# --- expiração e entrega -----------------------------------------------------------------------


def test_expire_due_so_abertas_vencidas():
    svc, repo, clock = make_service()
    due = _create(svc, "evento-1", consumption="consumo-1", expires_in=timedelta(hours=1))
    later = _create(svc, "evento-2", consumption="consumo-2", expires_in=timedelta(hours=10))
    answered = _create(svc, "evento-3", consumption="consumo-3", expires_in=timedelta(hours=1))
    personal = _budget(svc)  # sem expiração
    svc.respond(answered.notification.id, household_id=HOUSE, resident_id=ANA, action_id="mine")  # type: ignore[union-attr]
    clock.advance(hours=2)

    expired = svc.expire_due()
    assert [n.id for n in expired] == [due.notification.id]  # type: ignore[union-attr]
    assert all(n.status is NotificationStatus.expired for n in expired)
    assert repo.get(due.notification.id).status is NotificationStatus.expired  # type: ignore[union-attr]
    assert repo.get(later.notification.id).status is NotificationStatus.unread  # type: ignore[union-attr]
    assert repo.get(answered.notification.id).status is NotificationStatus.actioned  # type: ignore[union-attr]
    assert repo.get(personal.notification.id).status is NotificationStatus.unread  # type: ignore[union-attr]
    assert svc.expire_due() == []  # repetir o varrimento não faz nada


def test_view_de_expirada_mostra_expired_e_nao_responde():
    svc, _, clock = make_service()
    _create(svc, expires_in=timedelta(hours=1))
    clock.advance(hours=1)
    (view,) = svc.list_for(HOUSE, ANA)
    assert view.status is NotificationStatus.expired
    assert view.can_respond is False


def test_entrega_respeita_preferencias_no_fuso_da_casa():
    svc, _, clock = make_service()
    n = _budget(svc).notification
    assert n is not None
    prefs = NotificationPreferences(
        resident_id=ANA, quiet_hours=QuietHours(start=time(22, 0), end=time(8, 0))
    )
    assert svc.delivery(n, None) is Delivery.now
    assert svc.delivery(n, prefs) is Delivery.now  # 12:00 UTC = 12:00 em Lisboa (inverno)
    clock.advance(hours=11)  # 23:00 em Lisboa
    assert svc.delivery(n, prefs) is Delivery.deferred
    off = NotificationPreferences(resident_id=ANA, disabled_kinds=[NotificationKind.budget_alert])
    assert svc.delivery(n, off) is Delivery.suppressed


def test_relogio_injetado_e_unico():
    clock = FakeClock()
    svc, _, _ = make_service(clock)
    n = _create(svc).notification
    assert n is not None and n.created_at == clock.now


# --- casa do caminho e deduplicação com pedido vencido ----------------------------------------


def test_casa_errada_e_indistinguivel_de_notificacao_inexistente():
    svc, repo, _ = make_service()
    n = _create(svc).notification
    assert n is not None
    with pytest.raises(NotificationNotFoundError):
        svc.respond(n.id, household_id=OTHER_HOUSE, resident_id=ANA, action_id="mine")
    with pytest.raises(NotificationNotFoundError):
        svc.mark_read(n.id, household_id=OTHER_HOUSE, resident_id=ANA)
    assert repo.get(n.id).status is NotificationStatus.unread  # type: ignore[union-attr]


def test_pedido_vencido_fica_expired_antes_de_se_criar_o_novo():
    svc, repo, clock = make_service()
    first = _create(svc, "evento-1", expires_in=timedelta(hours=1)).notification
    assert first is not None
    clock.advance(hours=2)  # `unread` na base, mas vencido
    again = _create(svc, "evento-2").notification
    assert again is not None and again.id != first.id
    assert repo.get(first.id).status is NotificationStatus.expired  # type: ignore[union-attr]
    assert repo.get(again.id).status is NotificationStatus.unread  # type: ignore[union-attr]
