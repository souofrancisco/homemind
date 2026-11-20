"""Motor ligado ao barramento (SAFE-04, onda 3): base em memória, relógio simulado (o `ts` dos
eventos), `SimulatedExecutor` ou fakes. Nunca hardware, rede, LLM nem MCP; a escrita física
continua desligada e nenhum teste lhe toca."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.agent import (
    ActionExecutionResult,
    AutomationScope,
    AutomationStatus,
    DeviceCapability,
    ExecutionStatus,
    TriggerKind,
)
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.presence import PresenceState as P
from homemind.core.config import get_settings
from homemind.core.events import EventBus, load_events
from homemind.features.agent.execution import EXECUTOR_ATTR
from homemind.features.automations import repo, service
from homemind.features.automations import simulation as sim
from homemind.features.automations.engine import AutomationEngine, Firing
from homemind.features.automations.runner import CONSUMER, INPUT_TYPES, AutomationRunner
from homemind.features.automations.service import AutomationProposeIn, AutomationTriggerIn
from homemind.features.automations.tests.conftest import DEMO_PLUG, NOW, add_house

A = fx.HOUSEHOLD
REAL = Provenance(origin=Origin.real, kind=ValueKind.measured)
REAL_INF = Provenance(origin=Origin.real, kind=ValueKind.inferred)


def at(minutes: float):
    return NOW + timedelta(minutes=minutes)


def ramp(start: int, end: int, step: int = 3, w: float = 2000, **kw):
    return [sim.reading(at(m), w, **kw) for m in range(start, end + 1, step)]


class FakeExecutor:
    """Executor falso da casa real: regista as chamadas e devolve o desfecho pedido."""

    def __init__(self, mode="confirmed", delay=0.0):
        self.mode, self.calls, self.delay = mode, [], delay

    async def execute(self, action, confirmation):
        self.calls.append((action, confirmation))
        await asyncio.sleep(self.delay)
        if self.mode == "raise":
            raise RuntimeError("tomada sem resposta")
        return ActionExecutionResult(
            action_id=action.id, status=ExecutionStatus.confirmed, readback_confirmed=True,
            executed_at=NOW,
        )  # fmt: skip


def body(kind=TriggerKind.power_above, device=DEMO_PLUG, duration_s=600, target=None):
    trig = (
        AutomationTriggerIn(kind=kind, device_id=device, threshold_w=1500, duration_s=duration_s)
        if kind is TriggerKind.power_above
        else AutomationTriggerIn(kind=kind)
    )
    return AutomationProposeIn(
        name="Desligar a tomada", trigger=trig, target_device_id=target or device
    )


def activate(
    db, *, house=A, people=(fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO), origin=Origin.simulated,
    device=DEMO_PLUG, kind=TriggerKind.power_above, duration_s=600, target=None,
):  # fmt: skip
    """Propõe e aprova pela votação real (o proponente + os votos necessários)."""
    plugs = {device: "Tomada", **({target: "Alvo"} if target else {})}
    r = db.run_sync(
        lambda c: service.propose(
            c, household_id=house, resident_id=people[0],
            body=body(kind, device, duration_s, target), plugs=plugs, origin=origin, now=NOW,
        )
    )  # fmt: skip
    rule = r.view.id
    for who in people[1:]:
        db.run_sync(lambda c, who=who: service.vote(c, house, who, rule, True, NOW))
    return rule


def real_house(db, key="real"):
    house, tenants, _ = db.run_sync(lambda c: add_house(c, key, 3, source=hh.SourceKind.real))
    return house, tenants


def executed(db):
    return [s.event for s in db.run_sync(lambda c: load_events(c, types=["automation.executed"]))]


class Harness:
    """Uma «vida» do processo: barramento + motor. Reiniciar = criar outro sobre a mesma base."""

    def __init__(self, db, *, executor=None, engine=None):
        self.db = db
        self.state = SimpleNamespace()
        if executor is not None:
            setattr(self.state, EXECUTOR_ATTR, executor)
        self.runner = AutomationRunner(
            self.state, clock=lambda: NOW,
            engine=engine or AutomationEngine(device_cooldown_s=60, rule_cooldown_s=0),
        )  # fmt: skip
        self.bus = EventBus(db)

    async def __aenter__(self):
        self.runner.attach(self.bus)
        await self.bus.start()
        return self

    async def __aexit__(self, *_):
        await self.bus.stop()
        await self.runner.close()

    async def publish(self, *events):
        for e in events:
            await self.bus.publish(e)
        await self.settle()

    async def settle(self):
        marks = ",".join("?" * len(INPUT_TYPES))
        sql = (
            f"SELECT count(*) FROM domain_event d WHERE d.type IN ({marks}) AND NOT EXISTS"
            " (SELECT 1 FROM processed_event p WHERE p.consumer = ? AND p.event_id = d.id)"
        )
        for _ in range(500):
            if (
                self.db.run_sync(lambda c: c.execute(sql, (*INPUT_TYPES, CONSUMER)).fetchone()[0])
                == 0
            ):
                break
            await asyncio.sleep(0.01)
        await self.runner.idle()
        await asyncio.sleep(0.05)  # um disparo a caminho da fila
        await self.runner.idle()


def run(coro):
    return asyncio.run(coro)


# --- gatilho de potência -------------------------------------------------------------------


def test_demo_dispara_so_a_duracao_certa_com_o_executor_simulado_e_grava_o_resultado_real(db):
    rule = activate(db)

    async def go():
        async with Harness(db) as h:
            await h.publish(*ramp(0, 9))  # 9 min < 10 min: a meio da duração
            assert executed(db) == [] and h.state.__dict__ == {}
            await h.publish(sim.reading(at(12), 2000))
            await h.publish(*ramp(15, 60))  # a condição mantém-se: sem novo disparo
            return h.state.agent_simulated_executor

    simulated = run(go())
    (ev,) = executed(db)
    assert ev.data.rule_id == rule and ev.data.result.status is ExecutionStatus.confirmed
    assert ev.data.result.readback_confirmed and ev.provenance.simulated and ev.ts == at(12)
    assert simulated.read(DEMO_PLUG) == {DeviceCapability.power.value: False}  # só desliga
    assert get_settings().enable_physical_writes is False


def test_a_confirmacao_e_a_votacao_e_so_corre_com_a_regra_ativa_e_aprovada(db):
    house, tenants = real_house(db)
    fake = FakeExecutor()
    dev = stable_id("device", "tomada-real")
    rule = activate(db, house=house, people=tuple(tenants), origin=Origin.real, device=dev)
    approver = tenants[-1]  # quem deu o voto decisivo (unanimidade: o último a votar)
    row = db.run_sync(lambda c: repo.get_row(c, house, rule))
    assert UUID(row["approved_by_resident_id"]) == approver

    async def go():
        async with Harness(db, executor=fake) as h:
            await h.publish(*ramp(0, 12, device=dev, house=house, prov=REAL))

    run(go())
    ((action, confirmation),) = fake.calls
    assert confirmation.accepted and confirmation.resident_id == approver
    assert confirmation.action_id == action.id and action.status.value == "confirmed"
    assert "votação" in action.rationale and action.requires_confirmation
    assert (action.command.capability, action.command.power) == (DeviceCapability.power, False)
    assert action.command.target_device_id == dev
    assert not executed(db)[0].provenance.simulated


def test_casa_de_demonstracao_usa_sempre_o_simulado_mesmo_com_executor_registado(db):
    activate(db)
    fake = FakeExecutor()

    async def go():
        async with Harness(db, executor=fake) as h:
            await h.publish(*ramp(0, 12))
            return h.state.agent_simulated_executor

    simulated = run(go())
    assert fake.calls == [] and len(executed(db)) == 1  # nunca o executor «real»
    assert simulated.read(DEMO_PLUG)[DeviceCapability.power.value] is False


def test_regra_suspensa_proposta_ou_rejeitada_nunca_executa(db):
    suspended = activate(db)
    db.run_sync(lambda c: service.suspend(c, A, fx.ANA, suspended, NOW))
    pending = db.run_sync(  # só proposta (um voto em quatro)
        lambda c: service.propose(
            c,
            household_id=A,
            resident_id=fx.DIOGO,
            body=body(),
            plugs={DEMO_PLUG: "T"},
            origin=Origin.simulated,
            now=NOW,
        )
    ).view
    assert pending.status is AutomationStatus.proposed
    rejected = db.run_sync(
        lambda c: service.propose(
            c,
            household_id=A,
            resident_id=fx.CARLA,
            body=body(),
            plugs={DEMO_PLUG: "T"},
            origin=Origin.simulated,
            now=NOW,
        )
    ).view.id
    for who in (fx.ANA, fx.BRUNO, fx.DIOGO):
        db.run_sync(lambda c, who=who: service.vote(c, A, who, rejected, False, NOW))
    assert db.run_sync(lambda c: repo.get_row(c, A, rejected))["status"] == "draft"

    async def go():
        async with Harness(db) as h:
            await h.publish(*ramp(0, 30))
            # a suspensão vale na hora: um disparo já decidido antes dela não chega a executar
            f = Firing(suspended, A, DEMO_PLUG, stable_id("x"), at(31), TriggerKind.power_above)
            await h.runner._execute(f)

    run(go())
    assert executed(db) == []


def test_sem_executor_o_resultado_e_blocked_executor_unavailable_sem_tentar(db):
    house, tenants = real_house(db)
    dev = stable_id("device", "tomada-real")
    activate(db, house=house, people=tuple(tenants), origin=Origin.real, device=dev)

    async def go():
        async with Harness(db) as h:  # nada registado em `agent_action_executor`
            await h.publish(*ramp(0, 12, device=dev, house=house, prov=REAL))

    run(go())
    (ev,) = executed(db)
    res = ev.data.result
    assert (res.status, res.code, res.mcp_is_error) == (
        ExecutionStatus.blocked, "executor_unavailable", None,
    )  # fmt: skip


def test_resultado_incerto_nunca_se_repete_e_bloqueia_o_dispositivo(db):
    house, tenants = real_house(db)
    dev, fake = stable_id("device", "tomada-real"), FakeExecutor("raise")
    activate(db, house=house, people=tuple(tenants), origin=Origin.real, device=dev, duration_s=60)
    kw = {"device": dev, "house": house, "prov": REAL}

    def reads(*pairs):
        return [sim.reading(at(m), w, **kw) for m, w in pairs]

    async def go():
        engine = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0, lockout_s=300)
        async with Harness(db, executor=fake, engine=engine) as h:
            await h.publish(*reads((0, 2000), (1, 2000)))  # dispara: incerto
            await h.publish(*reads((2, 2000), (2.2, 2000)))  # a condição mantém-se
            assert len(fake.calls) == 1
            await h.publish(*reads((3, 0), (3.5, 2000), (4.5, 2000)))  # recomeça: 3,5 min depois
            assert len(fake.calls) == 1  # bloqueado: nem chegou ao executor
            fake.mode = "confirmed"
            await h.publish(*reads((5, 0), (400, 2000), (401, 2000)))  # bloqueio acabado

    run(go())
    results = [(e.data.result.status, e.data.result.code) for e in executed(db)]
    assert results == [
        (ExecutionStatus.uncertain, "executor_error"),
        (ExecutionStatus.blocked, "uncertain_lockout"),
        (ExecutionStatus.confirmed, None),
    ]
    assert len(fake.calls) == 2  # a incerta nunca foi repetida


def test_duas_regras_no_mesmo_dispositivo_executam_uma_so_vez(db):
    activate(db)
    activate(db, people=(fx.DIOGO, fx.BRUNO, fx.CARLA, fx.ANA))

    async def go():
        async with Harness(db) as h:
            await h.publish(*ramp(0, 12))
            return h.state.agent_simulated_executor

    run(go())
    assert len(executed(db)) == 1


def test_dois_eventos_concorrentes_executam_uma_so_vez(db):
    activate(db, kind=TriggerKind.presence_changed)

    async def go():
        async with Harness(db) as h:
            await h.publish(
                sim.presence(at(0), fx.ANA, P.home), sim.presence(at(0), fx.BRUNO, P.home)
            )
            await asyncio.gather(
                h.bus.publish(sim.presence(at(5), fx.ANA, P.away)),
                h.bus.publish(sim.presence(at(5), fx.BRUNO, P.away)),
            )
            await h.settle()
            return h.state.agent_simulated_executor

    simulated = run(go())
    results = [(e.data.result.status, e.data.result.code) for e in executed(db)]
    assert results.count((ExecutionStatus.confirmed, None)) == 1
    assert results.count((ExecutionStatus.blocked, "device_cooldown")) == 1
    assert simulated.read(DEMO_PLUG)["power"] is False


# --- presença ------------------------------------------------------------------------------


def test_presenca_que_muda_dispara_uma_vez_e_uma_repeticao_nao_dispara(db):
    activate(db, kind=TriggerKind.presence_changed)

    async def go():
        async with Harness(db) as h:
            await h.publish(sim.presence(at(0), fx.ANA, P.home))  # só regista o estado
            assert executed(db) == []
            await h.publish(sim.presence(at(5), fx.ANA, P.away))
            await h.publish(sim.presence(at(6), fx.ANA, P.away))  # igual: nada
            return h

    run(go())
    (ev,) = executed(db)
    assert ev.data.result.status is ExecutionStatus.confirmed and ev.ts == at(5)


# --- reinício e reentrega ------------------------------------------------------------------


def test_replay_depois_de_reiniciar_nao_duplica_e_o_estado_refaz_se(db):
    activate(db)

    async def life(events):
        async with Harness(db) as h:
            await h.publish(*events)

    run(life(ramp(0, 12)))
    assert len(executed(db)) == 1
    # reinício: a condição mantém-se (mesmo episódio) e eventos antigos não voltam a entregar-se
    run(life(ramp(15, 45)))
    assert len(executed(db)) == 1
    run(life([]))
    assert len(executed(db)) == 1


def test_o_bloqueio_por_incerteza_sobrevive_ao_reinicio(db):
    house, tenants = real_house(db)
    dev = stable_id("device", "tomada-real")
    activate(db, house=house, people=tuple(tenants), origin=Origin.real, device=dev, duration_s=60)
    kw = {"device": dev, "house": house, "prov": REAL}
    first, second = FakeExecutor("raise"), FakeExecutor()

    def reads(*pairs):
        return [sim.reading(at(m), w, **kw) for m, w in pairs]

    async def life(fake, events):
        engine = AutomationEngine(device_cooldown_s=0, rule_cooldown_s=0, lockout_s=300)
        async with Harness(db, executor=fake, engine=engine) as h:
            await h.publish(*events)

    run(life(first, reads((0, 2000), (1, 2000))))
    run(life(second, reads((2, 0), (3, 2000), (4, 2000))))  # reinício dentro do bloqueio
    assert len(first.calls) == 1 and second.calls == []  # bloqueado: nada tentado
    assert [e.data.result.code for e in executed(db)] == ["executor_error", "uncertain_lockout"]


def test_reentrega_do_barramento_nao_duplica(db):
    activate(db)

    async def go():
        async with Harness(db) as h:
            events = ramp(0, 12)
            await h.publish(*events)
            stored = db.run_sync(lambda c: load_events(c, types=["energy.reading_recorded"]))
            for s in stored:  # o barramento volta a entregar tudo: já estava processado
                assert await h.bus.deliver(CONSUMER, s) is False
            # o handler volta a correr depois de uma transação falhada: mesma decisão, sem fila
            for s in stored:
                db.run_sync(lambda c, s=s: h.runner.handle(c, s))
            await h.settle()

    run(go())
    assert len(executed(db)) == 1


def test_eventos_de_outra_casa_nao_disparam_regras_desta(db):
    activate(db)

    async def go():
        async with Harness(db) as h:
            await h.publish(*ramp(0, 30, house=fx.HOUSEHOLD, device=fx.PLUG_SALA))  # outra tomada

    run(go())
    assert executed(db) == []


def test_a_app_liga_o_motor_ao_barramento_no_arranque(app):
    assert isinstance(app.state.automations_runner, AutomationRunner)
    assert get_settings().enable_physical_writes is False


def test_o_bloqueio_volta_a_consultar_se_na_execucao_e_trava_um_disparo_ja_decidido(db):
    house, tenants = real_house(db)
    dev_a, dev_b = stable_id("device", "gatilho-a"), stable_id("device", "gatilho-b")
    plug, fake = stable_id("device", "tomada-real"), FakeExecutor("raise", delay=0.3)
    for trigger in (dev_a, dev_b):  # duas regras, gatilhos distintos, a mesma tomada
        activate(db, house=house, people=tuple(tenants), origin=Origin.real, device=trigger,
                 target=plug, duration_s=0)  # fmt: skip

    async def go():
        engine = AutomationEngine(device_cooldown_s=60, rule_cooldown_s=0, lockout_s=300)
        async with Harness(db, executor=fake, engine=engine) as h:
            a = sim.reading(at(0), 2000, device=dev_a, house=house, prov=REAL)
            b = sim.reading(at(2), 2000, device=dev_b, house=house, prov=REAL)
            # A e B ficam decididas antes de A terminar (incerta): B já não pode executar
            await h.bus.publish(a)
            await h.bus.publish(b)
            await h.settle()

    run(go())
    results = [(e.data.result.status, e.data.result.code) for e in executed(db)]
    assert sorted(results, key=str) == sorted(
        [
            (ExecutionStatus.uncertain, "executor_error"),
            (ExecutionStatus.blocked, "uncertain_lockout"),
        ],
        key=str,
    )
    assert len(fake.calls) == 1


def test_a_fila_de_deduplicacao_nao_cresce(db):
    activate(db)

    async def go():
        async with Harness(db) as h:
            await h.publish(*ramp(0, 12))
            assert len(executed(db)) == 1
            return h.runner._queued

    assert run(go()) == set()


def test_restore_so_le_a_janela_recente_e_mantem_o_estado(db):
    activate(db)

    async def life(events):
        async with Harness(db) as h:
            await h.publish(*events)

    old = [sim.reading(at(-4320), 100), sim.reading(at(-4317), 100)]  # há 3 dias
    run(life([sim.presence(at(-4320), fx.ANA, P.home), *old, *ramp(0, 12)]))
    assert len(executed(db)) == 1
    fresh = AutomationRunner(SimpleNamespace(), clock=lambda: NOW)
    n = db.run_sync(fresh.restore)
    assert n == 1 + 5  # a presença (toda) e as leituras recentes; as de há 3 dias ficam de fora
    run(life(ramp(15, 45)))  # o mesmo episódio depois de reiniciar: sem duplicar
    assert len(executed(db)) == 1


# --- regras individuais -----------------------------------------------------------------------


def personal_rule(db, house, owner, room, dev):
    body_ = body(device=dev).model_copy(update={"scope": AutomationScope.personal})
    r = db.run_sync(
        lambda c: service.propose(
            c,
            household_id=house,
            resident_id=owner,
            body=body_,
            plugs={dev: "Tomada do quarto"},
            origin=Origin.real,
            now=NOW,
            plug_rooms={dev: room},
        )
    )
    assert r.error is None and r.view.status is AutomationStatus.active
    return r.view.id


def test_individual_executa_sem_votacao_e_so_enquanto_o_dono_for_inquilino(db):
    house, tenants = real_house(db)
    dev = stable_id("device", "tomada-quarto-0")
    personal_rule(db, house, tenants[0], stable_id("room", "real", "0"), dev)
    fake = FakeExecutor()

    async def go():
        async with Harness(db, executor=fake) as h:
            await h.publish(*ramp(0, 12, device=dev, house=house, prov=REAL))

    run(go())
    ((action, confirmation),) = fake.calls
    assert action.command.target_device_id == dev
    assert confirmation.resident_id == tenants[0]  # a confirmação humana é a do dono


def test_individual_do_dono_que_saiu_nao_executa(db):
    house, tenants = real_house(db)
    dev = stable_id("device", "tomada-quarto-0")
    personal_rule(db, house, tenants[0], stable_id("room", "real", "0"), dev)
    db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-10' WHERE resident_id = ?",
            (str(tenants[0]),),
        )
    )
    fake = FakeExecutor()

    async def go():
        async with Harness(db, executor=fake) as h:
            await h.publish(*ramp(0, 12, device=dev, house=house, prov=REAL))

    run(go())
    assert fake.calls == [] and executed(db) == []
