"""AGENT-03, regressões da revisão de segurança (PR #171): relógio do executor, execução
interrompida, transições na base e filtros em SQL. Sem rede, LLM nem hardware."""

import asyncio
import sqlite3
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from homemind.contracts.agent import ActionExecutionResult, ExecutionStatus
from homemind.features.agent import actions, actions_router
from homemind.features.agent.actions import ActionLimits
from homemind.features.agent.config import AgentSettings
from homemind.features.agent.devices import DIRECTORY_ATTR
from homemind.features.agent.execution import EXECUTOR_ATTR
from homemind.features.agent.tests._action_fakes import (
    REAL_BULB,
    REAL_PLUG,
    FakeDirectory,
    FakeExecutor,
)
from homemind.features.agent.tests.conftest import GINA as GINA_ID
from homemind.features.agent.tests.conftest import HOUSE_C, as_

GINA = "sub-gina"
BASE = f"/api/households/{HOUSE_C}/agent"
LIMITS = ActionLimits(
    ttl_s=600, max_open=3, cooldown_s=60, max_per_hour=6, lockout_s=300, timeout_s=0.3
)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    s = AgentSettings(agent_action_timeout_s=0.3)
    monkeypatch.setattr(actions_router, "get_agent_settings", lambda: s)
    return s


def install(app, ex):
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([REAL_PLUG, REAL_BULB]))
    setattr(app.state, EXECUTOR_ATTR, ex)


def propose(client, text="desliga a tomada") -> UUID:
    r = client.post(f"{BASE}/messages", json={"text": text}, headers=as_(GINA))
    assert r.status_code == 200, r.text
    assert len(r.json()["proposed_actions"]) == 1, r.json()["text"]
    return UUID(r.json()["proposed_actions"][0]["id"])


def confirm(client, aid):
    return client.post(f"{BASE}/actions/{aid}/confirm", headers=as_(GINA))


def sql(app, query, args=()):
    return app.state.db.run_sync(lambda c: c.execute(query, args).fetchall())


class SkewedExecutor(FakeExecutor):
    """Declara um `executed_at` deslocado do relógio do servidor."""

    def __init__(self, clock, skew):
        super().__init__(clock)
        self.skew = skew

    async def execute(self, action, confirmation):
        self.calls.append((action, confirmation))
        return ActionExecutionResult(
            action_id=action.id, status=ExecutionStatus.confirmed, mcp_is_error=False,
            readback_confirmed=True, executed_at=self.clock() + self.skew,
        )  # fmt: skip


class CancelExecutor(FakeExecutor):
    async def execute(self, action, confirmation):
        self.calls.append((action, confirmation))
        raise asyncio.CancelledError  # cancelamento a meio da escrita


# --- M1: a coluna `executed_at` é a hora do servidor ---------------------------------------------


@pytest.mark.parametrize("skew", [timedelta(hours=-2), timedelta(hours=2)])
def test_instante_do_executor_fora_da_janela_e_resultado_invalido(app, real_house, now, skew):
    install(app, SkewedExecutor(lambda: now["value"], skew))
    client = TestClient(app)
    out = confirm(client, propose(client)).json()
    assert out["execution"]["status"] == "uncertain"
    assert out["execution"]["code"] == "invalid_result"


def test_relogio_do_executor_nao_anula_o_cooldown(app, real_house, now):
    """Mesmo um resultado gravado com `executed_at` de há 2 h conta como «agora» nos limites."""
    install(app, FakeExecutor(lambda: now["value"]))
    client = TestClient(app)
    first = propose(client)
    stale = ActionExecutionResult(
        action_id=first, status=ExecutionStatus.confirmed, readback_confirmed=True,
        mcp_is_error=False, executed_at=now["value"] - timedelta(hours=2),
    )  # fmt: skip

    def go(c):
        actions.confirm(c, HOUSE_C, GINA_ID, first, now["value"], LIMITS)
        return actions.record_execution(c, HOUSE_C, GINA_ID, first, stale, now["value"])

    assert app.state.db.run_sync(go) is not None
    (row,) = sql(
        app, "SELECT executed_at, execution_json FROM agent_action WHERE id = ?", (str(first),)
    )
    assert row["executed_at"] == now["value"].isoformat()  # hora do servidor
    assert "10:00:00Z" in row["execution_json"]  # o do executor fica só no JSON
    now["value"] += timedelta(seconds=10)
    out = confirm(client, propose(client)).json()
    assert out["execution"]["code"] == "cooldown"


def test_limite_por_hora_resiste_a_relogio_atrasado(app, real_house, now):
    install(app, FakeExecutor(lambda: now["value"]))
    client = TestClient(app)
    for _ in range(8):
        aid = propose(client)

        def go(c, aid=aid):
            actions.confirm(c, HOUSE_C, GINA_ID, aid, now["value"], LIMITS)
            stale = ActionExecutionResult(
                action_id=aid, status=ExecutionStatus.confirmed, readback_confirmed=True,
                mcp_is_error=False, executed_at=now["value"] - timedelta(hours=3),
            )  # fmt: skip
            actions.record_execution(c, HOUSE_C, GINA_ID, aid, stale, now["value"])

        app.state.db.run_sync(go)
        now["value"] += timedelta(seconds=61)  # fora do cooldown, a hora conta
    out = confirm(client, propose(client)).json()
    assert out["execution"]["code"] == "hourly_limit"


# --- M2: execução interrompida -------------------------------------------------------------------


def test_cancelamento_a_meio_fica_incerto_interrompido_e_bloqueia(app, real_house, now):
    ex = CancelExecutor(lambda: now["value"])
    install(app, ex)
    client = TestClient(app, raise_server_exceptions=False)
    aid = propose(client)
    try:
        confirm(client, aid)
    except BaseException:  # noqa: BLE001, S110 - o cancelamento pode atravessar o TestClient
        pass
    (row,) = sql(app, "SELECT status, execution_status FROM agent_action WHERE id = ?", (str(aid),))
    assert (row["status"], row["execution_status"]) == ("executed", "uncertain")
    (log_row,) = sql(
        app,
        "SELECT code FROM agent_action_log WHERE action_id = ? AND to_status = 'executed'",
        (str(aid),),
    )
    assert log_row["code"] == "interrupted"
    view = client.get(f"{BASE}/actions/{aid}", headers=as_(GINA)).json()
    assert view["execution"]["code"] == "interrupted"
    assert "pode ter sido aplicado" in view["message"] and "Não repito" in view["message"]

    good = FakeExecutor(lambda: now["value"])
    install(app, good)
    now["value"] += timedelta(seconds=120)  # fora do cooldown, dentro do bloqueio de 5 min
    out = confirm(client, propose(client)).json()
    assert out["execution"]["code"] == "uncertain_lockout" and good.calls == []
    assert len(ex.calls) == 1  # nunca reexecutada


def test_confirmada_sem_desfecho_e_resolvida_na_leitura(app, real_house, now):
    """Crash entre o COMMIT da confirmação e o desfecho: a leitura resolve-a como incerta."""
    ex = FakeExecutor(lambda: now["value"])
    install(app, ex)
    client = TestClient(app)
    aid = propose(client)
    app.state.db.run_sync(lambda c: actions.confirm(c, HOUSE_C, GINA_ID, aid, now["value"], LIMITS))
    view = client.get(f"{BASE}/actions/{aid}", headers=as_(GINA)).json()
    assert view["action"]["status"] == "confirmed" and view["execution"] is None  # ainda em curso
    now["value"] += timedelta(seconds=LIMITS.stale_s + 1)
    view = client.get(f"{BASE}/actions/{aid}", headers=as_(GINA)).json()
    assert view["execution"]["status"] == "uncertain" and view["execution"]["code"] == "interrupted"
    assert "Não repito" in view["message"]
    assert ex.calls == []


def test_confirmada_antiga_conta_como_incerta_nos_limites(app, real_house, now):
    ex = FakeExecutor(lambda: now["value"])
    install(app, ex)
    client = TestClient(app)
    aid = propose(client)
    app.state.db.run_sync(lambda c: actions.confirm(c, HOUSE_C, GINA_ID, aid, now["value"], LIMITS))
    now["value"] += timedelta(seconds=LIMITS.stale_s + 61)  # fora do cooldown, sem leitura
    out = confirm(client, propose(client)).json()
    assert out["execution"]["code"] == "uncertain_lockout" and ex.calls == []


# --- L2: a base recusa transições inválidas ------------------------------------------------------


def test_base_recusa_confirmed_sem_confirmacao_e_regressoes(app, real_house, now):
    install(app, FakeExecutor(lambda: now["value"]))
    client = TestClient(app)
    aid = propose(client)
    with pytest.raises(sqlite3.IntegrityError):  # confirmed sem confirmation_json
        sql(app, "UPDATE agent_action SET status = 'confirmed' WHERE id = ?", (str(aid),))
    with pytest.raises(sqlite3.IntegrityError):  # proposed → executed salta a confirmação
        sql(app, "UPDATE agent_action SET status = 'executed' WHERE id = ?", (str(aid),))
    assert confirm(client, aid).status_code == 200  # o fluxo normal continua a passar
    for target in ("proposed", "rejected", "expired"):  # executed é terminal
        with pytest.raises(sqlite3.IntegrityError):
            sql(app, "UPDATE agent_action SET status = ? WHERE id = ?", (target, str(aid)))
    other = propose(client, "desliga a luz")
    client.post(f"{BASE}/actions/{other}/reject", headers=as_(GINA))
    for target in ("proposed", "confirmed"):  # rejected é terminal
        with pytest.raises(sqlite3.IntegrityError):
            sql(app, "UPDATE agent_action SET status = ? WHERE id = ?", (target, str(other)))


# --- L3: filtro e limite em SQL ------------------------------------------------------------------


def test_lista_com_filtro_derivado_e_limite(app, real_house, now):
    install(app, FakeExecutor(lambda: now["value"]))
    client = TestClient(app)
    old = propose(client, "desliga a tomada")
    now["value"] += timedelta(seconds=LIMITS.ttl_s + 1)  # a primeira expira (derivado)
    fresh = [propose(client, "desliga a luz")]
    rejected = propose(client, "desliga a luz")
    client.post(f"{BASE}/actions/{rejected}/reject", headers=as_(GINA))

    def ids(q):
        r = client.get(f"{BASE}/actions{q}", headers=as_(GINA))
        assert r.status_code == 200
        return [x["action"]["id"] for x in r.json()]

    assert ids("?status=expired") == [str(old)]
    assert ids("?status=proposed") == [str(f) for f in fresh]
    assert ids("?status=rejected") == [str(rejected)]
    assert ids("?limit=1") == [str(rejected)]
    assert ids("") == [str(rejected), *map(str, fresh), str(old)]
    assert ids("?status=expired&limit=1") == [str(old)]
