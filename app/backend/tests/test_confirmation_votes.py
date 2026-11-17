"""Regra B — votação «De quem é esta conta?» (D-32). Dados SIMULADOS das fixtures (4 inquilinos)."""

from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts import notification as nt
from homemind.contracts.common import replace

V = nt.ConfirmationVerdict
T = fx.T0 + timedelta(minutes=1)


def vote(n, who, action, target=None, minute=1):
    return n.respond(who, action, fx.T0 + timedelta(minutes=minute), target_resident_id=target)


def test_metade_arredondada_para_cima():
    assert [nt.votes_needed(k) for k in (1, 2, 3, 4, 5, 6)] == [1, 1, 2, 2, 3, 3]


def test_um_e_minha_basta_e_fecha():
    n = vote(fx.confirmation_notification(), fx.CARLA, "mine")
    out = n.outcome(T)
    assert n.status is nt.NotificationStatus.actioned
    assert (out.verdict, out.resident_id, out.votes) == (V.self_claimed, fx.CARLA, 1)
    with pytest.raises(nt.AlreadyRespondedError):
        vote(n, fx.ANA, "everyone")


def test_atribuir_a_outro_precisa_de_metade():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    assert n.status is nt.NotificationStatus.unread and n.outcome(T).verdict is V.pending
    assert not n.can_respond(fx.ANA, T) and n.can_respond(fx.CARLA, T)  # um voto por pessoa
    n = vote(n, fx.CARLA, "other", fx.BRUNO, minute=2)
    out = n.outcome(T)
    assert (out.verdict, out.resident_id, out.votes_needed) == (
        V.accusation_accepted,
        fx.BRUNO,
        2,
    )
    assert n.status is nt.NotificationStatus.actioned and n.response.resident_id == fx.CARLA


def test_o_proprio_assume_antes_de_chegar_a_metade():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    n = vote(n, fx.BRUNO, "mine", minute=2)
    out = n.outcome(T)
    assert (out.verdict, out.resident_id) == (V.self_claimed, fx.BRUNO)


def test_votos_divididos_entre_alvos_nao_decidem():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    n = vote(n, fx.CARLA, "other", fx.DIOGO, minute=2)
    assert n.outcome(T).verdict is V.pending
    n = vote(n, fx.BRUNO, "everyone", minute=3)
    n = vote(n, fx.DIOGO, "unknown", minute=4)
    out = n.outcome(T)  # todos votaram sem decisão → por todos
    assert out.verdict is V.everyone and out.resident_id is None
    assert n.status is nt.NotificationStatus.actioned


def test_expira_inconclusivo_divide_por_todos():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    late = n.expires_at + timedelta(seconds=1)
    assert n.outcome(late).verdict is V.everyone
    with pytest.raises(nt.NotificationExpiredError):
        n.respond(fx.CARLA, "other", late, target_resident_id=fx.BRUNO)


def test_alvos_invalidos():
    n = fx.confirmation_notification()
    with pytest.raises(nt.InvalidTargetError):
        vote(n, fx.ANA, "other")  # sem alvo
    with pytest.raises(nt.InvalidTargetError):
        vote(n, fx.ANA, "other", fx.ANA)  # a si próprio é «É minha»
    with pytest.raises(nt.InvalidTargetError):
        vote(n, fx.ANA, "other", fx.LANDLORD)  # o senhorio nunca paga consumos da casa
    with pytest.raises(nt.InvalidTargetError):
        vote(n, fx.ANA, "mine", fx.BRUNO)  # alvo só com `other`


def test_outros_tipos_mantem_uma_so_resposta():
    n = fx.confirmation_notification()
    base = n.model_dump() | {"kind": nt.NotificationKind.agent_action, "expires_at": None}
    single = nt.Notification.model_validate(base)
    with pytest.raises(nt.InvalidTargetError):
        single.respond(fx.ANA, "other", T, target_resident_id=fx.BRUNO)
    done = single.respond(fx.ANA, "everyone", T)
    assert done.status is nt.NotificationStatus.actioned and done.responses == []


def test_invariantes_da_notificacao():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    with pytest.raises(ValueError):
        replace(n, status=nt.NotificationStatus.actioned, response=n.responses[0])  # não decidida
    decided = vote(n, fx.CARLA, "mine", minute=2)
    with pytest.raises(ValueError):
        replace(decided, status=nt.NotificationStatus.read, response=None)  # decidida e aberta


def test_vista_mostra_votos_sem_revelar_quem_votou():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    view = nt.NotificationView.for_resident(n, fx.CARLA, T)
    v = view.voting
    assert (v.verdict, v.votes, v.eligible, v.votes_needed, v.my_vote) == (V.pending, 1, 4, 2, None)
    assert [(a.target_resident_id, a.votes) for a in v.accusations] == [(fx.BRUNO, 1)]
    assert str(fx.ANA) not in view.model_dump_json()  # quem votou não aparece
    mine = nt.NotificationView.for_resident(n, fx.ANA, T).voting.my_vote
    assert mine.by_me and mine.target_resident_id == fx.BRUNO
    closed = vote(n, fx.BRUNO, "mine", minute=2)
    assert nt.NotificationView.for_resident(closed, fx.BRUNO, T).voting.pays_me
    assert not nt.NotificationView.for_resident(closed, fx.CARLA, T).voting.pays_me


def test_confirmation_outcome_rejeita_votos_repetidos():
    n = vote(fx.confirmation_notification(), fx.ANA, "other", fx.BRUNO)
    with pytest.raises(ValueError):
        nt.confirmation_outcome([*n.responses, *n.responses], n.responder_ids)
