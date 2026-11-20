"""SAFE-04: propor, votar, expirar, suspender e reativar as regras da casa. Base em memória,
relógio simulado, nada de rede nem hardware; a regra nunca chega a executar nada."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from homemind.contracts import fixtures as fx
from homemind.contracts.agent import (
    AutomationRule,
    AutomationScope,
    AutomationStatus,
    RuleVerdict,
    TriggerKind,
)
from homemind.contracts.common import Origin, stable_id
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
    assert (v.votes_for, v.votes_against, v.eligible, v.majority, v.my_vote) == (1, 0, 4, 4, True)
    assert v.origin is Origin.simulated and v.message.startswith("SIMULADO")
    assert types(db, "automation.proposed") == ["automation.proposed"]
    assert types(db, "automation.vote_decided", "automation.status_changed") == []
    assert [e.type for e in r.events] == ["automation.proposed"]  # com 4 moradores faltam 3 votos


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


# --- unanimidade (D-39) ------------------------------------------------------------------------


@pytest.mark.parametrize("n,needed", [(2, 2), (3, 3), (4, 4)])
def test_unanimidade_ativa_a_regra_com_quem_deu_o_ultimo_voto(db, n, needed):
    house, tenants = house_of(db, n)
    rule = propose(db, house, tenants[0]).view.id
    for i, who in enumerate(tenants[1:needed]):  # o proponente já votou a favor ao propor
        r = vote(db, rule, who, house=house)
        assert r.error is None
        if i < needed - 2:
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


def test_tres_votos_a_favor_nao_chegam_com_quatro_moradores(db):
    rule = propose(db).view.id
    vote(db, rule, fx.BRUNO)
    r = vote(db, rule, fx.CARLA)  # a Ana (proponente) já contava: 3 de 4 necessários
    assert r.view.status is AutomationStatus.proposed and r.events == ()
    assert (r.view.votes_for, r.view.majority) == (3, 4)
    assert "4 de 4" in r.view.message and "todos os moradores" in r.view.message


def test_um_voto_contra_rejeita_logo_proposed_para_draft_so_com_vote_decided(db):
    house, tenants = house_of(db, 3)
    rule = propose(db, house, tenants[0]).view.id
    r = vote(db, rule, tenants[1], False, house=house)  # os outros nem chegam a votar
    assert r.view.status is AutomationStatus.draft and not r.view.vote_open
    assert r.view.last_verdict is RuleVerdict.rejected
    assert types(db, "automation.vote_decided") == ["automation.vote_decided"]
    assert types(db, "automation.status_changed") == []
    (ev,) = [
        s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.vote_decided"]))
    ]
    assert ev.data.verdict is RuleVerdict.rejected and ev.data.expired is False
    assert (ev.data.votes_for, ev.data.votes_against, ev.data.eligible) == (1, 1, 3)


def test_voto_repetido_e_recusado_e_nao_conta_duas_vezes(db):
    rule = propose(db).view.id
    assert vote(db, rule, fx.ANA).error == service.ALREADY_VOTED  # o proponente já votou
    assert vote(db, rule, fx.BRUNO).error is None
    assert vote(db, rule, fx.BRUNO, False).error == service.ALREADY_VOTED
    v = listing(db, who=fx.BRUNO)[0][0]
    assert (v.votes_for, v.votes_against, v.my_vote) == (2, 0, True)


def test_voto_do_senhorio_ou_de_quem_nao_estava_na_ronda_e_recusado(db):
    rule = propose(db).view.id
    for who in (fx.LANDLORD, fx.OPERATOR):
        assert vote(db, rule, who).error == service.NOT_ELIGIBLE
    assert listing(db)[0][0].votes_for == 1  # só o do proponente


def test_regra_de_outra_casa_nao_existe(db):
    rule = propose(db).view.id
    assert vote(db, rule, fx.ANA, house=HOUSE_B).error == service.NOT_FOUND


# --- prazo ---------------------------------------------------------------------------------


def test_voto_depois_de_24h_nunca_conta_e_a_regra_fica_rejeitada(db):
    rule = propose(db).view.id
    late = NOW + timedelta(hours=24)  # o prazo acaba exatamente às 24 h
    r = vote(db, rule, fx.BRUNO, at=late)
    assert r.error == service.VOTE_EXPIRED
    assert [e.type for e in r.events] == ["automation.vote_decided"]
    v = listing(db, at=late)[0][0]
    assert v.status is AutomationStatus.draft and v.last_verdict is RuleVerdict.rejected
    assert v.votes_for == 1  # o voto tardio nunca entrou


def test_expirar_sem_todos_os_votos_rejeita_e_e_idempotente(db):
    propose(db)
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
    db.run_sync(
        lambda c: c.execute(
            "INSERT INTO automation_vote (rule_id, resident_id, approve, at) VALUES (?,?,1,?)",
            (str(rule), str(tenants[1]), (NOW + timedelta(hours=30)).isoformat()),
        )
    )
    later = NOW + timedelta(hours=31)
    (v,), _ = db.run_sync(lambda c: service.list_views(c, house, tenants[0], later))
    assert v.status is AutomationStatus.draft and v.votes_for == 1  # 1 de 2: sem unanimidade


# --- concorrência ----------------------------------------------------------------------------


def test_dois_votos_contra_em_simultaneo_so_um_decide(db):
    async def go():
        house, tenants = house_of(db, 3)
        rule = propose(db, house, tenants[0]).view.id
        return (
            rule,
            house,
            tenants,
            await asyncio.gather(
                db.run(lambda c: service.vote(c, house, tenants[1], rule, False, NOW)),
                db.run(lambda c: service.vote(c, house, tenants[2], rule, False, NOW)),
            ),
        )

    rule, house, tenants, results = asyncio.run(go())
    assert sorted(r.error or "ok" for r in results) == sorted([service.VOTE_NOT_OPEN, "ok"])
    assert len(types(db, "automation.vote_decided")) == 1
    assert types(db, "automation.status_changed") == []  # rejeitada: `proposed → draft`


def test_o_fecho_e_um_compare_and_set_sobre_a_versao_lida(db):
    house, tenants = house_of(db, 2)
    rule = propose(db, house, tenants[0]).view.id
    stale = db.run_sync(lambda c: repo.get_row(c, house, rule))  # lida antes de alguém decidir
    vote(db, rule, tenants[1], house=house)  # decide (rev avança)

    def late(c):
        out, n = service._outcome(c, stale, expired=False)
        service._close(c, stale, out, n, NOW, by=tenants[1], expired=False)

    with pytest.raises(ConflictError):
        db.run_sync(late)
    assert len(types(db, "automation.vote_decided")) == 1  # a transação perdida voltou atrás


# --- suspender e reativar ----------------------------------------------------------------------


def active_rule(db, house=A, voters=(fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO)):
    rule = propose(db, house, voters[0]).view.id
    for who in voters[1:]:  # o proponente já votou a favor ao propor
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


def test_reativar_abre_nova_votacao_limpa_e_so_a_unanimidade_ativa(db):
    rule = active_rule(db)
    suspend(db, rule, fx.DIOGO)
    r = reactivate(db, rule, fx.DIOGO)
    v = r.view
    assert v.status is AutomationStatus.disabled and v.vote_open and v.vote_round == 2
    assert (v.votes_for, v.votes_against, v.my_vote) == (0, 0, None)  # ronda limpa
    assert [e.type for e in r.events] == ["automation.proposed"]  # aviso da nova ronda
    assert reactivate(db, rule, fx.ANA).error == service.VOTE_ALREADY_OPEN
    vote(db, rule, fx.ANA)
    assert listing(db)[0][0].status is AutomationStatus.disabled  # um voto não chega
    vote(db, rule, fx.BRUNO)
    vote(db, rule, fx.CARLA)
    assert listing(db)[0][0].status is AutomationStatus.disabled  # três em quatro não chegam
    done = vote(db, rule, fx.DIOGO)
    assert done.view.status is AutomationStatus.active
    assert [e.type for e in done.events] == ["automation.vote_decided", "automation.status_changed"]
    assert UUID(row(db, rule)["approved_by_resident_id"]) == fx.DIOGO
    assert len(types(db, "automation.vote_decided")) == 2  # uma por ronda


def test_reativar_so_com_regra_suspensa_e_por_inquilino(db):
    rule = active_rule(db)
    assert reactivate(db, rule, fx.ANA).error == service.NOT_DISABLED  # ativa
    suspend(db, rule, fx.ANA)
    assert reactivate(db, rule, fx.LANDLORD).error == service.NOT_ELIGIBLE


def test_reativacao_sem_unanimidade_no_prazo_deixa_a_regra_suspensa(db):
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
    assert kinds == ["proposed", "voted", "voted", "voted", "voted", "decided", "suspended"]
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


# --- proponente, 1 morador, limite, reativação, device_id ---------------------------------------


def test_o_proponente_conta_como_um_voto_a_favor(db):
    r = propose(db)
    v = r.view
    assert (v.votes_for, v.majority, v.my_vote) == (1, 4, True)  # faltam 3 votos
    assert v.status is AutomationStatus.proposed
    assert vote(db, v.id, fx.ANA).error == service.ALREADY_VOTED
    other = listing(db, who=fx.BRUNO)[0][0]
    assert other.my_vote is None and other.votes_for == 1  # a contagem é igual para todos


def test_com_um_so_morador_a_regra_fecha_aprovada_no_proprio_pedido(db):
    house, (only,) = house_of(db, 1)
    r = propose(db, house, only)
    assert r.error is None and r.view.status is AutomationStatus.active
    assert [e.type for e in r.events] == [
        "automation.proposed",
        "automation.vote_decided",
        "automation.status_changed",
    ]
    stored = db.run_sync(lambda c: repo.get_row(c, house, r.view.id))
    assert UUID(stored["approved_by_resident_id"]) == only and not stored["vote_open"]
    assert types(db, "automation.proposed") == ["automation.proposed"]  # uma só vez


def test_limite_de_tres_propostas_abertas_por_proponente(db):
    for _ in range(service.MAX_OPEN_PER_PROPOSER):
        assert propose(db).error is None
    assert propose(db).error == service.TOO_MANY_OPEN
    assert len(types(db, "automation.proposed")) == 3
    assert propose(db, who=fx.BRUNO).error is None  # o limite é por proponente
    # uma proposta que fecha (prazo) liberta lugar
    later = NOW + timedelta(hours=25)
    assert propose(db, at=later).error is None


def test_reativar_conta_para_o_limite_de_tres_votacoes_abertas(db):
    rule = active_rule(db)
    suspend(db, rule, fx.DIOGO)
    for _ in range(service.MAX_OPEN_PER_PROPOSER):
        assert propose(db, who=fx.DIOGO).error is None
    r = reactivate(db, rule, fx.DIOGO)
    assert r.error == service.TOO_MANY_OPEN and r.view is None
    assert reactivate(db, rule, fx.ANA).error is None  # o limite é por pessoa


def test_reativar_com_menos_de_tres_abertas_abre_a_votacao_e_ocupa_um_lugar(db):
    rule = active_rule(db)
    suspend(db, rule, fx.DIOGO)
    for _ in range(service.MAX_OPEN_PER_PROPOSER - 1):
        assert propose(db, who=fx.DIOGO).error is None
    assert reactivate(db, rule, fx.DIOGO).error is None
    assert propose(db, who=fx.DIOGO).error == service.TOO_MANY_OPEN  # a reativação ocupa lugar


def test_reativar_reemite_automation_proposed_com_id_por_ronda(db):
    rule = active_rule(db)
    suspend(db, rule, fx.DIOGO)
    r = reactivate(db, rule, fx.DIOGO)
    (notice,) = r.events
    assert notice.type == "automation.proposed" and notice.data.status is AutomationStatus.disabled
    assert notice.id == stable_id("automation.proposed", str(rule), "2")
    initial = [
        s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.proposed"]))
    ]
    assert [e.data.status for e in initial] == [
        AutomationStatus.proposed,
        AutomationStatus.disabled,
    ]
    assert initial[0].id == stable_id("automation.proposed", str(rule))  # ronda 1 inalterada
    assert len({e.id for e in initial}) == 2


def test_device_id_do_gatilho_de_outra_casa_e_recusado(db):
    other_house_plug = stable_id("device", "tomada-da-casa-b")
    body = proposal().model_copy(
        update={
            "trigger": AutomationTriggerIn(
                kind=TriggerKind.power_above,
                device_id=other_house_plug,
                threshold_w=1500,
                duration_s=1800,
            )
        }
    )
    assert propose(db, body=body).error == service.INVALID_TARGET  # o alvo é válido, o gatilho não
    assert types(db, "automation.proposed") == []
    lamp_trigger = body.model_copy(
        update={"trigger": body.trigger.model_copy(update={"device_id": LAMP})}
    )
    assert propose(db, body=lamp_trigger).error == service.INVALID_TARGET  # a lâmpada não mede


# --- regras individuais (D-39) -------------------------------------------------------------------

PLUG_ANA = stable_id("device", "tomada-quarto-ana")
PLUG_BRUNO = stable_id("device", "tomada-quarto-bruno")
PLUG_NAMES = {**plugs(), PLUG_ANA: "Tomada do quarto da Ana", PLUG_BRUNO: "Tomada do Bruno"}
PLUG_ROOMS = {DEMO_PLUG: fx.ROOM_SALA, PLUG_ANA: fx.ROOM_ANA, PLUG_BRUNO: fx.ROOM_BRUNO}


def personal(db, who=fx.ANA, body=None, at=NOW, rooms=PLUG_ROOMS, house=A):
    body = body or proposal(PLUG_ANA)
    body = body.model_copy(update={"scope": AutomationScope.personal})
    return db.run_sync(
        lambda c: service.propose(
            c, household_id=house, resident_id=who, body=body, plugs=PLUG_NAMES,
            origin=Origin.simulated, now=at, plug_rooms=rooms,
        )
    )  # fmt: skip


def test_individual_nasce_ativa_sem_votacao_sem_evento_e_sem_aviso(db):
    r = personal(db)
    assert r.error is None and r.events == ()
    v = r.view
    assert v.scope is AutomationScope.personal and v.status is AutomationStatus.active
    assert not v.vote_open and v.proposed_by_me and v.my_vote is None
    assert (v.votes_for, v.votes_against, v.eligible, v.majority) == (0, 0, 1, 1)
    assert "Só tu a vês" in v.message
    assert types(db, "automation.proposed", "automation.vote_decided") == []
    assert types(db, "automation.status_changed") == []
    stored = row(db, v.id)
    assert UUID(stored["approved_by_resident_id"]) == fx.ANA and not stored["vote_open"]
    assert stored["scope"] == "personal" and UUID(stored["owner_resident_id"]) == fx.ANA
    rule = repo.rule_of(stored)
    assert rule.scope is AutomationScope.personal and rule.owner_resident_id == fx.ANA
    kinds = db.run_sync(lambda c: c.execute("SELECT kind, code FROM automation_log").fetchall())
    assert [tuple(k) for k in kinds] == [("proposed", "personal")]
    ((found, since),) = db.run_sync(lambda c: repo.active_rules(c, A, NOW))
    assert found.id == v.id and since == NOW  # o motor apanha-a


def test_individual_so_em_tomadas_do_quarto_do_dono(db):
    assert personal(db, body=proposal(DEMO_PLUG)).error == service.INVALID_TARGET  # zona comum
    assert personal(db, body=proposal(PLUG_BRUNO)).error == service.INVALID_TARGET  # outro quarto
    mixed = proposal(PLUG_ANA).model_copy(  # alvo no quarto, gatilho noutra divisão
        update={
            "trigger": AutomationTriggerIn(
                kind=TriggerKind.power_above, device_id=DEMO_PLUG, threshold_w=1500, duration_s=60
            )
        }
    )
    assert personal(db, body=mixed).error == service.INVALID_TARGET
    assert personal(db, rooms={}).error == service.INVALID_TARGET  # divisão desconhecida
    assert personal(db, rooms={PLUG_ANA: None}).error == service.INVALID_TARGET
    assert personal(db, body=proposal(LAMP)).error == service.INVALID_TARGET
    assert personal(db, who=fx.LANDLORD).error == service.NOT_ELIGIBLE
    assert personal(db, who=fx.OPERATOR).error == service.NOT_ELIGIBLE
    # o dono da outra divisão pode usar a sua
    assert personal(db, who=fx.BRUNO, body=proposal(PLUG_BRUNO)).error is None
    assert personal(db, who=fx.BRUNO, body=proposal(PLUG_ANA)).error == service.INVALID_TARGET
    count = db.run_sync(lambda c: c.execute("SELECT count(*) FROM automation_rule").fetchone()[0])
    assert count == 1


def test_individual_e_privada_so_o_dono_a_ve_e_a_toca(db):
    rule = personal(db).view.id
    mine = listing(db, who=fx.ANA)
    assert [v.id for v in mine[0]] == [rule]
    for who in (fx.BRUNO, fx.CARLA, fx.LANDLORD, fx.OPERATOR):
        assert listing(db, who=who)[0] == []
        assert db.run_sync(lambda c, w=who: service.get_view(c, A, w, rule, NOW))[0] is None
        assert vote(db, rule, who).error == service.NOT_FOUND
        assert suspend(db, rule, who).error == service.NOT_FOUND
        assert reactivate(db, rule, who).error == service.NOT_FOUND
    assert row(db, rule)["status"] == "active"  # nada mudou
    assert vote(db, rule, fx.ANA).error == service.VOTE_NOT_OPEN  # nem o dono vota
    mixed = propose(db, who=fx.BRUNO).view.id  # uma regra da casa continua visível a todos
    assert [v.id for v in listing(db, who=fx.ANA)[0]] == [mixed, rule]
    assert [v.id for v in listing(db, who=fx.BRUNO)[0]] == [mixed]


def test_individual_so_o_dono_suspende_e_reativa_na_hora_sem_votacao(db):
    rule = personal(db).view.id
    paused = suspend(db, rule, fx.ANA)
    assert paused.error is None and paused.events == ()
    assert paused.view.status is AutomationStatus.disabled and not paused.view.vote_open
    assert db.run_sync(lambda c: repo.active_rules(c, A, NOW)) == []
    assert suspend(db, rule, fx.ANA).error == service.NOT_ACTIVE
    later = NOW + timedelta(minutes=5)
    back = reactivate(db, rule, fx.ANA, at=later)
    assert back.error is None and back.events == ()
    v = back.view
    assert v.status is AutomationStatus.active and not v.vote_open and v.vote_round == 1
    ((found, since),) = db.run_sync(lambda c: repo.active_rules(c, A, later))
    assert found.id == rule and since == later  # a ativação conta desde a reativação
    assert reactivate(db, rule, fx.ANA, at=later).error == service.NOT_DISABLED
    assert types(db, "automation.proposed", "automation.status_changed") == []
    kinds = db.run_sync(lambda c: [r[0] for r in c.execute("SELECT kind FROM automation_log")])
    assert kinds == ["proposed", "suspended", "decided"]


def test_individual_de_quem_saiu_da_casa_deixa_de_estar_ativa_para_o_motor(db):
    rule = personal(db).view.id
    house_rule = active_rule(db)
    assert {r.id for r, _ in db.run_sync(lambda c: repo.active_rules(c, A, NOW))} == {
        rule,
        house_rule,
    }
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-10'"
            " WHERE household_id = ? AND resident_id = ?",
            (str(A), str(fx.ANA)),
        )
    )
    left = {r.id for r, _ in db.run_sync(lambda c: repo.active_rules(c, A, NOW))}
    assert left == {house_rule}  # a da casa continua; a individual do dono que saiu, não


def test_regra_antiga_sem_scope_le_se_como_regra_da_casa(db):
    rule = propose(db).view.id
    old = row(db, rule)["json"]
    data = json.loads(old)
    assert data["scope"] == "house"
    data.pop("scope"), data.pop("owner_resident_id")
    db.run_sync(
        lambda c: c.execute(
            "UPDATE automation_rule SET json = ? WHERE id = ?", (json.dumps(data), str(rule))
        )
    )
    loaded = repo.rule_of(row(db, rule))
    assert loaded.scope is AutomationScope.house and loaded.owner_resident_id is None
    assert row(db, rule)["scope"] == "house"  # a coluna também predefine para `house`
    assert [v.scope for v in listing(db, who=fx.BRUNO)[0]] == [AutomationScope.house]
    assert isinstance(loaded, AutomationRule)


def test_dono_que_saiu_nao_reativa_a_sua_individual(db):
    rule = personal(db).view.id
    suspend(db, rule, fx.ANA)
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-10' WHERE resident_id = ?",
            (str(fx.ANA),),
        )
    )
    assert reactivate(db, rule, fx.ANA).error == service.NOT_ELIGIBLE
