"""SAFE-04: propor, votar, expirar, suspender e reativar as regras da casa. Base em memória,
relógio simulado, nada de rede nem hardware; a regra nunca chega a executar nada."""

import asyncio
import sqlite3
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from homemind.contracts import fixtures as fx
from homemind.contracts.agent import AutomationStatus, RuleVerdict, TriggerKind
from homemind.contracts.common import Origin
from homemind.core.events import load_events
from homemind.features.automations import repo, service
from homemind.features.automations.service import (
    VOTE_WINDOW,
    AutomationTriggerIn,
    ConflictError,
)
from homemind.features.automations.tests.conftest import (
    DEMO_PLUG,
    HOUSE_B,
    LAMP,
    NOW,
    add_house,
    plugs,
    proposal,
)

A = fx.HOUSEHOLD


def propose(db, house=A, who=fx.ANA, body=None, at=NOW, origin=Origin.simulated):
    return db.run_sync(
        lambda c: service.propose(
            c, household_id=house, resident_id=who, body=body or proposal(), plugs=plugs(),
            origin=origin, now=at,
        )
    )  # fmt: skip


def vote(db, rule_id, who, approve=True, at=NOW, house=A):
    return db.run_sync(lambda c: service.vote(c, house, who, rule_id, approve, at))


def suspend(db, rule_id, who, at=NOW, house=A):
    return db.run_sync(lambda c: service.suspend(c, house, who, rule_id, at))


def reactivate(db, rule_id, who, at=NOW, house=A):
    return db.run_sync(lambda c: service.reactivate(c, house, who, rule_id, at))


def listing(db, who=fx.ANA, at=NOW, house=A):
    return db.run_sync(lambda c: service.list_views(c, house, who, at))


def types(db, *wanted):
    return [s.event.type for s in db.run_sync(lambda c: load_events(c, types=wanted))]


def house_of(db, n):
    house, tenants, _ = db.run_sync(lambda c: add_house(c, f"h{n}", n))
    return house, tenants


def row(db, rule_id):
    return db.run_sync(lambda c: repo.get_row(c, A, rule_id))


# --- propor --------------------------------------------------------------------------------


def test_propor_grava_proposed_com_prazo_de_24h_e_emite_o_evento_uma_vez(db):
    r = propose(db)
    assert r.error is None
    v = r.view
    assert v.status is AutomationStatus.proposed and v.vote_open and v.proposed_by_me
    assert v.vote_deadline == NOW + VOTE_WINDOW == NOW + timedelta(hours=24)
    assert (v.votes_for, v.votes_against, v.eligible, v.majority, v.my_vote) == (0, 0, 4, 3, None)
    assert v.origin is Origin.simulated and v.message.startswith("SIMULADO")
    assert types(db, "automation.proposed") == ["automation.proposed"]
    # nunca se propõe duas vezes o mesmo evento: o id é estável e a regra é nova
    assert types(db, "automation.vote_decided", "automation.status_changed") == []


def test_so_inquilinos_ativos_propoem(db):
    for who in (fx.LANDLORD, fx.OPERATOR):
        assert propose(db, who=who).error == service.NOT_ELIGIBLE
    assert (
        db.run_sync(lambda c: c.execute("SELECT count(*) FROM automation_rule").fetchone()[0]) == 0
    )
    assert types(db, "automation.proposed") == []


def test_alvo_que_nao_e_tomada_conhecida_e_recusado_e_a_lampada_nunca_e_alvo(db):
    assert propose(db, body=proposal(LAMP)).error == service.INVALID_TARGET  # a lâmpada
    assert propose(db, body=proposal(fx.PLUG_SALA)).error == service.INVALID_TARGET  # desconhecida
    assert types(db, "automation.proposed") == []


def test_gatilho_incoerente_viola_o_contrato(db):
    body = proposal()
    bad = body.model_copy(update={"trigger": AutomationTriggerIn(kind=TriggerKind.power_above)})
    with pytest.raises(ValidationError):
        propose(db, body=bad)
    assert types(db, "automation.proposed") == []


def test_a_unica_acao_e_desligar_a_tomada(db):
    rule = propose(db).view.id
    (action,) = db.run_sync(lambda c: repo.rule_of(repo.get_row(c, A, rule))).actions
    assert (action.target_device_id, action.capability.value, action.power) == (
        DEMO_PLUG, "power", False,
    )  # fmt: skip


def test_casa_real_marca_origem_real_sem_etiqueta_simulado(db):
    house, tenants = house_of(db, 2)
    r = db.run_sync(
        lambda c: service.propose(
            c, household_id=house, resident_id=tenants[0], body=proposal(), plugs=plugs(),
            origin=Origin.real, now=NOW,
        )
    )  # fmt: skip
    assert r.view.origin is Origin.real and "SIMULADO" not in r.view.message


# --- maioria absoluta ------------------------------------------------------------------------


@pytest.mark.parametrize("n,needed", [(2, 2), (3, 2), (4, 3)])
def test_maioria_absoluta_ativa_a_regra_com_quem_deu_o_voto_decisivo(db, n, needed):
    house, tenants = house_of(db, n)
    rule = propose(db, house, tenants[0]).view.id
    for i, who in enumerate(tenants[:needed]):
        r = vote(db, rule, who, house=house)
        assert r.error is None
        if i < needed - 1:
            assert r.view.status is AutomationStatus.proposed and r.events == ()
    v = r.view
    assert v.status is AutomationStatus.active and not v.vote_open
    assert (v.votes_for, v.eligible, v.majority) == (needed, n, needed)
    assert v.last_verdict is RuleVerdict.approved
    stored = db.run_sync(lambda c: repo.get_row(c, house, rule))
    assert UUID(stored["approved_by_resident_id"]) == tenants[needed - 1]  # o voto decisivo
    assert types(db, "automation.vote_decided", "automation.status_changed") == [
        "automation.vote_decided",
        "automation.status_changed",
    ]
    (decided,) = [
        s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.vote_decided"]))
    ]
    assert decided.data.verdict is RuleVerdict.approved and decided.data.expired is False
    # votar depois de decidida: nada se repete
    assert vote(db, rule, tenants[-1], house=house).error == service.VOTE_NOT_OPEN
    assert len(types(db, "automation.vote_decided")) == 1


def test_um_voto_a_favor_nao_chega_com_quatro_moradores(db):
    rule = propose(db).view.id
    for who in (fx.ANA, fx.BRUNO):
        r = vote(db, rule, who)
    assert (
        r.view.status is AutomationStatus.proposed
        and r.view.votes_for == 2
        and r.view.majority == 3
    )


def test_maioria_impossivel_rejeita_proposed_para_draft_so_com_vote_decided(db):
    house, tenants = house_of(db, 3)
    rule = propose(db, house, tenants[0]).view.id
    vote(db, rule, tenants[0], False, house=house)
    r = vote(db, rule, tenants[1], False, house=house)
    assert r.view.status is AutomationStatus.draft and not r.view.vote_open
    assert r.view.last_verdict is RuleVerdict.rejected
    assert types(db, "automation.vote_decided") == ["automation.vote_decided"]
    assert types(db, "automation.status_changed") == []
    (ev,) = [
        s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.vote_decided"]))
    ]
    assert ev.data.verdict is RuleVerdict.rejected and ev.data.expired is False
    assert (ev.data.votes_for, ev.data.votes_against, ev.data.eligible) == (0, 2, 3)


def test_voto_repetido_e_recusado_e_nao_conta_duas_vezes(db):
    rule = propose(db).view.id
    assert vote(db, rule, fx.ANA).error is None
    assert vote(db, rule, fx.ANA, False).error == service.ALREADY_VOTED
    v = listing(db)[0][0]
    assert (v.votes_for, v.votes_against, v.my_vote) == (1, 0, True)


def test_voto_do_senhorio_ou_de_quem_nao_estava_na_ronda_e_recusado(db):
    rule = propose(db).view.id
    for who in (fx.LANDLORD, fx.OPERATOR):
        assert vote(db, rule, who).error == service.NOT_ELIGIBLE
    assert listing(db)[0][0].votes_for == 0


def test_regra_de_outra_casa_nao_existe(db):
    rule = propose(db).view.id
    assert vote(db, rule, fx.ANA, house=HOUSE_B).error == service.NOT_FOUND


# --- prazo ---------------------------------------------------------------------------------


def test_voto_depois_de_24h_nunca_conta_e_a_regra_fica_rejeitada(db):
    rule = propose(db).view.id
    vote(db, rule, fx.ANA)
    late = NOW + timedelta(hours=24)  # o prazo acaba exatamente às 24 h
    r = vote(db, rule, fx.BRUNO, at=late)
    assert r.error == service.VOTE_EXPIRED
    assert [e.type for e in r.events] == ["automation.vote_decided"]
    v = listing(db, at=late)[0][0]
    assert v.status is AutomationStatus.draft and v.last_verdict is RuleVerdict.rejected
    assert v.votes_for == 1  # o voto tardio nunca entrou


def test_expirar_sem_maioria_rejeita_e_e_idempotente(db):
    rule = propose(db).view.id
    vote(db, rule, fx.ANA)
    later = NOW + timedelta(hours=25)
    first, events = db.run_sync(lambda c: service.list_views(c, A, fx.ANA, later))
    assert first[0].status is AutomationStatus.draft and [e.type for e in events] == [
        "automation.vote_decided"
    ]
    again, events2 = db.run_sync(lambda c: service.list_views(c, A, fx.ANA, later))
    assert events2 == () and again[0].status is AutomationStatus.draft
    (ev,) = [
        s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.vote_decided"]))
    ]
    assert ev.data.expired is True and ev.data.verdict is RuleVerdict.rejected
    assert types(db, "automation.status_changed") == []
    assert (
        db.run_sync(
            lambda c: c.execute("SELECT code FROM automation_log WHERE kind='decided'").fetchone()[
                0
            ]
        )
        == "expired"
    )


def test_votos_fora_de_prazo_nao_entram_na_contagem_nem_aprovam(db):
    """Um voto gravado depois do prazo (ex.: relógio errado) é filtrado antes da função pura."""
    house, tenants = house_of(db, 2)
    rule = propose(db, house, tenants[0]).view.id
    vote(db, rule, tenants[0], house=house)
    db.run_sync(
        lambda c: c.execute(
            "INSERT INTO automation_vote (rule_id, resident_id, approve, at) VALUES (?,?,1,?)",
            (str(rule), str(tenants[1]), (NOW + timedelta(hours=30)).isoformat()),
        )
    )
    later = NOW + timedelta(hours=31)
    (v,), _ = db.run_sync(lambda c: service.list_views(c, house, tenants[0], later))
    assert v.status is AutomationStatus.draft and v.votes_for == 1  # 1 de 2: sem maioria


# --- concorrência ----------------------------------------------------------------------------


def test_dois_votos_finais_em_simultaneo_so_um_decide(db):
    async def go():
        house, tenants = house_of(db, 3)
        rule = propose(db, house, tenants[0]).view.id
        vote(db, rule, tenants[0], house=house)
        return (
            rule,
            house,
            tenants,
            await asyncio.gather(
                db.run(lambda c: service.vote(c, house, tenants[1], rule, True, NOW)),
                db.run(lambda c: service.vote(c, house, tenants[2], rule, True, NOW)),
            ),
        )

    rule, house, tenants, results = asyncio.run(go())
    assert sorted(r.error or "ok" for r in results) == sorted([service.VOTE_NOT_OPEN, "ok"])
    assert len(types(db, "automation.vote_decided")) == 1
    assert len(types(db, "automation.status_changed")) == 1


def test_o_fecho_e_um_compare_and_set_sobre_a_versao_lida(db):
    house, tenants = house_of(db, 2)
    rule = propose(db, house, tenants[0]).view.id
    stale = db.run_sync(lambda c: repo.get_row(c, house, rule))  # lida antes de alguém decidir
    vote(db, rule, tenants[0], house=house)
    vote(db, rule, tenants[1], house=house)  # decide (rev avança)

    def late(c):
        out, n = service._outcome(c, stale, expired=False)
        service._close(c, stale, out, n, NOW, by=tenants[1], expired=False)

    with pytest.raises(ConflictError):
        db.run_sync(late)
    assert len(types(db, "automation.vote_decided")) == 1  # a transação perdida voltou atrás


# --- suspender e reativar ----------------------------------------------------------------------


def active_rule(db, house=A, voters=(fx.ANA, fx.BRUNO, fx.CARLA)):
    rule = propose(db, house, voters[0]).view.id
    for who in voters:
        vote(db, rule, who, house=house)
    return rule


def test_qualquer_inquilino_suspende_e_o_evento_diz_quem(db):
    rule = active_rule(db)
    r = suspend(db, rule, fx.DIOGO)  # nem propôs nem votou
    assert r.view.status is AutomationStatus.disabled and not r.view.vote_open
    (ev,) = [
        s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.status_changed"]))
    ][-1:]
    assert (ev.data.from_status, ev.data.to_status, ev.data.resident_id) == (
        AutomationStatus.active, AutomationStatus.disabled, fx.DIOGO,
    )  # fmt: skip
    assert suspend(db, rule, fx.ANA).error == service.NOT_ACTIVE  # repetido: não faz nada
    assert len(types(db, "automation.status_changed")) == 2  # a ativação e a suspensão


def test_so_se_suspende_uma_regra_ativa(db):
    rule = propose(db).view.id
    assert suspend(db, rule, fx.ANA).error == service.NOT_ACTIVE  # ainda por votar
    assert suspend(db, fx.PLUG_SALA, fx.ANA).error == service.NOT_FOUND


def test_reativar_abre_nova_votacao_limpa_e_so_a_maioria_ativa(db):
    rule = active_rule(db)
    suspend(db, rule, fx.DIOGO)
    r = reactivate(db, rule, fx.DIOGO)
    v = r.view
    assert v.status is AutomationStatus.disabled and v.vote_open and v.vote_round == 2
    assert (v.votes_for, v.votes_against, v.my_vote) == (0, 0, None)  # ronda limpa
    assert r.events == ()
    assert reactivate(db, rule, fx.ANA).error == service.VOTE_ALREADY_OPEN
    vote(db, rule, fx.ANA)
    assert listing(db)[0][0].status is AutomationStatus.disabled  # um voto não chega
    vote(db, rule, fx.BRUNO)
    done = vote(db, rule, fx.CARLA)
    assert done.view.status is AutomationStatus.active
    assert [e.type for e in done.events] == ["automation.vote_decided", "automation.status_changed"]
    assert UUID(row(db, rule)["approved_by_resident_id"]) == fx.CARLA
    assert len(types(db, "automation.vote_decided")) == 2  # uma por ronda


def test_reativar_so_com_regra_suspensa_e_por_inquilino(db):
    rule = active_rule(db)
    assert reactivate(db, rule, fx.ANA).error == service.NOT_DISABLED  # ativa
    suspend(db, rule, fx.ANA)
    assert reactivate(db, rule, fx.LANDLORD).error == service.NOT_ELIGIBLE


def test_reativacao_sem_maioria_no_prazo_deixa_a_regra_suspensa(db):
    rule = active_rule(db)
    suspend(db, rule, fx.ANA)
    reactivate(db, rule, fx.ANA)
    vote(db, rule, fx.ANA)
    later = NOW + timedelta(hours=25)
    (v,), events = db.run_sync(lambda c: service.list_views(c, A, fx.ANA, later))
    assert v.status is AutomationStatus.disabled and not v.vote_open
    assert [e.type for e in events] == ["automation.vote_decided"]
    assert v.last_verdict is RuleVerdict.rejected
    assert db.run_sync(lambda c: service.list_views(c, A, fx.ANA, later))[1] == ()
    assert reactivate(db, rule, fx.ANA, at=later).error is None  # pode tentar outra vez


# --- registo e eventos ---------------------------------------------------------------------------


def test_log_so_acrescenta(db):
    rule = active_rule(db)
    suspend(db, rule, fx.ANA)
    kinds = [
        r[0]
        for r in db.run_sync(
            lambda c: c.execute("SELECT kind FROM automation_log ORDER BY seq").fetchall()
        )
    ]
    assert kinds == ["proposed", "voted", "voted", "voted", "decided", "suspended"]
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: c.execute("UPDATE automation_log SET kind = 'voted'"))
    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: c.execute("DELETE FROM automation_log"))


def test_a_base_recusa_transicoes_invalidas(db):
    rule = propose(db).view.id
    with pytest.raises(sqlite3.IntegrityError):  # proposed → disabled não existe
        db.run_sync(lambda c: c.execute("UPDATE automation_rule SET status = 'disabled'"))
    with pytest.raises(sqlite3.IntegrityError):  # active sem aprovação
        db.run_sync(lambda c: c.execute("UPDATE automation_rule SET status = 'active'"))
    assert row(db, rule)["status"] == "proposed"
