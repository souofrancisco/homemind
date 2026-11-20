"""Motor puro das regras da casa (SAFE-04): o «agora» é o `ts` do evento, sem I/O nem relógio."""

from datetime import timedelta

from homemind.contracts import fixtures as fx
from homemind.contracts.agent import AutomationScope, ExecutionStatus, TriggerKind
from homemind.contracts.common import replace
from homemind.contracts.presence import PresenceState as P
from homemind.features.automations import simulation as sim
from homemind.features.automations.engine import (
    DEVICE_COOLDOWN,
    MAX_READING_GAP,
    RULE_COOLDOWN,
    UNCERTAIN_LOCKOUT,
    ActiveRule,
    AutomationEngine,
)

T0 = fx.T0
OTHER = fx.PLUG_SALA


def at(minutes: float):
    return T0 + timedelta(minutes=minutes)


def active(*rules, since=T0):
    return [ActiveRule(r, since) for r in rules]


def feed(engine, events, rules):
    return [f for e in events for f in engine.on_event(e, rules)]


def watts(engine, rules, series):
    """`series` = [(minuto, potência)] -> disparos."""
    return feed(engine, [sim.reading(at(m), w) for m, w in series], rules)


def test_a_meio_da_duracao_nao_dispara_e_dispara_a_duracao_certa():
    eng, rules = AutomationEngine(), active(sim.power_rule(duration_s=600))
    assert watts(eng, rules, [(0, 2000), (3, 2000), (6, 2000), (9, 2000)]) == []  # 9 min < 10 min
    # leituras a cada 3 min: abaixo do intervalo máximo, a sequência mantém-se
    (f,) = watts(eng, rules, [(12, 2000)])
    assert f.at == at(12) and f.cause is TriggerKind.power_above and f.blocked_code is None
    assert f.device_id == fx.METER and f.rule_id == rules[0].rule.id


def test_um_disparo_por_episodio_enquanto_a_condicao_se_mantem():
    eng, rules = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0), active(sim.power_rule())
    got = watts(eng, rules, [(m, 2000) for m in range(0, 60, 2)])
    assert len(got) == 1 and got[0].at == at(10)


def test_condicao_que_quebra_recomeca_do_zero():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    rules = active(sim.power_rule(duration_s=600))
    series = [(0, 2000), (5, 2000), (6, 100), (7, 2000), (11, 2000), (15, 2000), (17, 2000)]
    got = watts(eng, rules, series)
    assert [f.at for f in got] == [at(17)]  # 10 min desde o recomeço em 7


def test_exatamente_no_limiar_nao_conta():
    eng, rules = AutomationEngine(), active(sim.power_rule(threshold_w=1500, duration_s=0))
    assert watts(eng, rules, [(0, 1500), (5, 1500)]) == []
    assert len(watts(eng, rules, [(6, 1500.5)])) == 1


def test_leitura_sem_potencia_ou_intervalo_longo_quebra_a_sequencia():
    from homemind.contracts.energy import ReadingStatus

    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    rules = active(sim.power_rule(duration_s=600))
    events = [
        sim.reading(at(0), 2000), sim.reading(at(5), 2000),
        sim.reading(at(6), None, status=ReadingStatus.missing),  # não prova nada
        sim.reading(at(9), 2000), sim.reading(at(12), 2000),  # só 3 min desde o recomeço
    ]  # fmt: skip
    assert feed(eng, events, rules) == []
    gap = (MAX_READING_GAP + timedelta(minutes=1)).total_seconds() / 60
    assert watts(eng, rules, [(12 + gap, 2000)]) == []  # intervalo grande: recomeça aí
    assert len(watts(eng, rules, [(12 + gap + 5, 2000), (12 + gap + 10, 2000)])) == 1


def test_leituras_fora_de_ordem_ou_repetidas_ignoram_se():
    eng, rules = AutomationEngine(), active(sim.power_rule(duration_s=300))
    assert watts(eng, rules, [(0, 2000), (4, 2000), (2, 2000), (4, 2000)]) == []
    assert len(watts(eng, rules, [(5, 2000)])) == 1


def test_fecho_do_consumo_e_outro_dispositivo_e_outra_casa():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    rules = active(sim.power_rule(duration_s=600))
    assert feed(eng, [sim.reading(at(0), 2000), sim.reading(at(5), 2000)], rules) == []
    eng.on_event(sim.closed(at(6)), rules)  # o consumo fechou: nova sequência
    assert watts(eng, rules, [(7, 2000), (12, 2000)]) == []
    assert len(watts(eng, rules, [(17, 2000)])) == 1
    # leituras de outro dispositivo nunca contam
    other = [sim.reading(at(m), 3000, device=OTHER) for m in (30, 45)]
    assert feed(eng, other, rules) == []


def test_so_regras_ativas_e_so_eventos_desde_a_ativacao():
    eng = AutomationEngine()
    suspended = sim.power_rule(status=sim.AutomationStatus.disabled)
    assert watts(eng, active(suspended)[:0], [(0, 2000), (20, 2000)]) == []  # não está ativa
    rules = active(sim.power_rule(duration_s=0), since=at(10))
    assert watts(eng, rules, [(5, 2000)]) == []  # anterior à ativação
    assert len(watts(eng, rules, [(10, 2000)])) == 1


def test_regra_suspensa_perde_a_sequencia_e_reativada_recomeca():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    rule = sim.power_rule(duration_s=600)
    assert watts(eng, active(rule), [(0, 2000), (5, 2000)]) == []
    eng.on_event(sim.reading(at(6), 2000), [])  # suspensa: já não vem na lista
    again = active(rule, since=at(8))  # reativada (nova votação) às 8
    assert watts(eng, again, [(9, 2000), (14, 2000)]) == []  # recomeço em 9, não em 0
    assert len(watts(eng, again, [(19, 2000)])) == 1


def test_duas_regras_no_mesmo_dispositivo_geram_um_so_disparo():
    eng = AutomationEngine()
    a, b = sim.power_rule("a", duration_s=0), sim.power_rule("b", duration_s=0)
    rules = active(a, b)
    (f,) = eng.on_event(sim.reading(at(0), 2000), rules)
    lead, other = sorted([a.id, b.id], key=str)
    assert f.rule_id == lead and f.covered == (other,) and f.blocked_code is None


def test_regras_em_dispositivos_diferentes_disparam_cada_uma():
    eng = AutomationEngine()
    a = sim.power_rule("a", duration_s=0)
    b = sim.power_rule("b", duration_s=0, target=OTHER)
    got = eng.on_event(sim.reading(at(0), 2000), active(a, b))
    assert {f.device_id for f in got} == {fx.METER, OTHER}


def test_cooldown_da_regra_e_do_dispositivo_regista_o_bloqueio_sem_executar():
    eng = AutomationEngine(device_cooldown_s=600, rule_cooldown_s=3600)
    a = sim.power_rule("a", duration_s=0)
    b = sim.power_rule(
        "b", duration_s=0, target=fx.METER, device=OTHER
    )  # mesmo alvo, outro gatilho
    rules = active(a, b)
    assert eng.on_event(sim.reading(at(0), 2000), rules)[0].blocked_code is None
    eng.on_event(sim.reading(at(1), 100), rules)  # episódio acaba
    # a regra a volta a querer disparar 5 min depois: cooldown da regra
    assert eng.on_event(sim.reading(at(5), 2000), rules)[0].blocked_code == RULE_COOLDOWN
    # a regra b (nunca disparou) no mesmo alvo: cooldown do dispositivo
    got = eng.on_event(sim.reading(at(6), 2000, device=OTHER), rules)
    assert [f.blocked_code for f in got] == [DEVICE_COOLDOWN]
    # passado o cooldown da regra e do dispositivo volta a executar
    eng.on_event(sim.reading(at(70), 100), rules)
    assert eng.on_event(sim.reading(at(71), 2000), rules)[0].blocked_code is None


def test_resultado_incerto_bloqueia_o_dispositivo_ate_ao_fim_do_bloqueio():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0, lockout_s=300)
    rules = active(sim.power_rule(duration_s=0))
    assert eng.on_event(sim.reading(at(0), 2000), rules)[0].blocked_code is None
    eng.record_result(fx.METER, ExecutionStatus.uncertain, at(0))
    eng.on_event(sim.reading(at(1), 0), rules)
    assert eng.on_event(sim.reading(at(2), 2000), rules)[0].blocked_code == UNCERTAIN_LOCKOUT
    eng.on_event(sim.reading(at(3), 0), rules)
    assert eng.on_event(sim.reading(at(6), 2000), rules)[0].blocked_code is None  # 6 min > 5
    # resultados confirmados/bloqueados/falhados não bloqueiam
    for s in (ExecutionStatus.confirmed, ExecutionStatus.failed, ExecutionStatus.blocked):
        eng.record_result(fx.METER, s, at(6))
    eng.on_event(sim.reading(at(7), 0), rules)
    assert eng.on_event(sim.reading(at(7.5), 2000), rules)[0].blocked_code is not UNCERTAIN_LOCKOUT


def test_presenca_dispara_so_quando_o_estado_muda():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    rules = active(sim.presence_rule())
    assert eng.on_event(sim.presence(at(0), fx.ANA, P.home), rules) == []  # primeira observação
    assert eng.on_event(sim.presence(at(1), fx.ANA, P.home), rules) == []  # igual
    (f,) = eng.on_event(sim.presence(at(2), fx.ANA, P.away), rules)
    assert f.cause is TriggerKind.presence_changed and f.device_id == fx.METER
    # outro morador tem o seu próprio estado
    assert eng.on_event(sim.presence(at(3), fx.BRUNO, P.away), rules) == []
    assert len(eng.on_event(sim.presence(at(4), fx.BRUNO, P.home), rules)) == 1


def test_presenca_sem_regras_ativas_continua_a_registar_o_estado():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    eng.on_event(sim.presence(at(0), fx.ANA, P.home), [])
    got = eng.on_event(
        sim.presence(at(1), fx.ANA, P.away), active(sim.presence_rule(), since=at(1))
    )
    assert len(got) == 1


def test_repetir_os_mesmos_eventos_num_motor_novo_da_as_mesmas_decisoes():
    events = [sim.reading(at(m), 2000) for m in range(0, 30, 3)]
    rules = active(sim.power_rule(duration_s=600))
    first = feed(AutomationEngine(), events, rules)
    assert first == feed(AutomationEngine(), events, rules) and len(first) == 1


def test_transicoes_com_incerto_nao_disparam_mas_o_estado_fica_registado():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    rules = active(sim.presence_rule())
    eng.on_event(sim.presence(at(0), fx.ANA, P.home), rules)
    assert eng.on_event(sim.presence(at(1), fx.ANA, P.uncertain), rules) == []  # in -> incerto
    assert eng.on_event(sim.presence(at(2), fx.ANA, P.away), rules) == []  # incerto -> out
    assert eng.on_event(sim.presence(at(3), fx.ANA, P.uncertain), rules) == []
    assert eng.on_event(sim.presence(at(4), fx.ANA, P.uncertain), rules) == []
    assert eng.on_event(sim.presence(at(5), fx.ANA, P.away), rules) == []  # incerto -> out
    assert len(eng.on_event(sim.presence(at(6), fx.ANA, P.home), rules)) == 1  # out -> in


def test_regra_individual_de_presenca_so_dispara_com_as_transicoes_do_dono():
    eng = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0)
    mine = replace(
        sim.presence_rule("pessoal"), scope=AutomationScope.personal, owner_resident_id=fx.ANA
    )
    rules = active(mine)
    eng.on_event(sim.presence(at(0), fx.BRUNO, P.home), rules)
    assert eng.on_event(sim.presence(at(1), fx.BRUNO, P.away), rules) == []  # o Bruno não conta
    eng.on_event(sim.presence(at(2), fx.ANA, P.home), rules)
    (f,) = eng.on_event(sim.presence(at(3), fx.ANA, P.away), rules)  # a Ana (dona) sim
    assert f.cause is TriggerKind.presence_changed and f.rule_id == mine.id
    # a regra da casa continua a disparar com qualquer morador
    eng2, house_rules = AutomationEngine(), active(sim.presence_rule())
    eng2.on_event(sim.presence(at(0), fx.BRUNO, P.home), house_rules)
    assert len(eng2.on_event(sim.presence(at(1), fx.BRUNO, P.away), house_rules)) == 1
