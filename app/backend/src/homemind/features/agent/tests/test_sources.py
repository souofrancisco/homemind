"""Escolha dos providers: real registado → SIMULADO (só casa demo) → sem dados. Sem rede nem LLM."""

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.features.agent import providers as providers_mod
from homemind.features.agent.formatting import format_eur, format_kwh
from homemind.features.agent.providers import REGISTRY_ATTR, ProviderSet, ToolValue
from homemind.features.agent.sources import get_registered, resolve
from homemind.features.agent.tests._fakes import NOW, FakeLLM
from homemind.features.agent.tests.conftest import as_
from homemind.features.agent.tools import ToolContext, ToolRegistry
from homemind.features.households.repo import (
    insert_household,
    insert_membership,
    insert_resident,
    insert_room,
)

REAL_HOUSE = stable_id("household", "casa-real")
REAL_ROOM = stable_id("room", "casa-real-quarto")
RITA = stable_id("resident", "rita")
LANDLORD_REAL = stable_id("resident", "senhorio-real")
OPERATOR_REAL = stable_id("resident", "operador-real")
REAL_BILL = stable_id("bill", "real-1")
OTHER_BILL = stable_id("bill", "real-2")
PERIOD = "2026-11"

REAL = Provenance(origin=Origin.real, kind=ValueKind.measured)
SIM = Provenance(origin=Origin.simulated, kind=ValueKind.measured)


def url(house) -> str:
    return f"/api/households/{house}/agent/messages"


# --- fakes (no próprio ficheiro) ------------------------------------------------------------------


class FakeReal:
    """Provider real configurável; regista chamadas. `error` levanta em todas as leituras."""

    def __init__(
        self,
        *,
        consumption: ToolValue | None = None,
        budget: ToolValue | None = None,
        receipt: ToolValue | None = None,
        bill: tuple[UUID, str] | None = None,
        error: Exception | None = None,
    ):
        self._v = {"consumption": consumption, "budget": budget, "receipt": receipt}
        self._bill = bill
        self.error = error
        self.calls: list[str] = []

    def _read(self, name: str):
        self.calls.append(name)
        if self.error:
            raise self.error
        return self._v[name]

    def consumption_summary(self, household_id, resident_id, period):
        return self._read("consumption")

    def budget_status(self, household_id, resident_id, period):
        return self._read("budget")

    def receipt(self, household_id, resident_id, bill_id):
        return self._read("receipt")

    def latest_bill(self, household_id, resident_id):
        self.calls.append("latest_bill")
        if self.error:
            raise self.error
        return self._bill


class FakeAppliances:
    def top_appliances(self, household_id, resident_id, period, limit=5):
        return ToolValue(None, 100, SIM), []


def value(prov: Provenance = REAL, wh: int = 4_321, cents: int = 1_234) -> ToolValue:
    return ToolValue(energy_wh=wh, cost_cents=cents, provenance=prov)


def ctx_for(household: UUID, resident: UUID, role: str = "tenant") -> ToolContext:
    return ToolContext(
        household_id=household,
        resident_id=resident,
        role=hh.MembershipRole(role),
        now=NOW,
        period=PERIOD,
    )


def registry(registered: ProviderSet, household: UUID, source_kind: str) -> ToolRegistry:
    return ToolRegistry(*resolve(registered, household, source_kind))


# --- app: casa real no próprio ficheiro ----------------------------------------------------------


def seed_real_house(conn) -> None:
    insert_household(
        conn,
        hh.Household(
            id=REAL_HOUSE,
            name="Casa real",
            settings=hh.HouseholdSettings(source_kind=hh.SourceKind.real),
            created_at=fx.T0,
        ),
    )
    insert_room(
        conn,
        hh.Room(id=REAL_ROOM, household_id=REAL_HOUSE, name="Quarto", kind=hh.RoomKind.bedroom),
    )
    for rid, name in (
        (RITA, "Rita"),
        (LANDLORD_REAL, "Senhorio real"),
        (OPERATOR_REAL, "Operador real"),
    ):
        insert_resident(conn, hh.Resident(id=rid, display_name=name, auth_subject=f"sub-{rid}"))
    for res, role, room in (
        (RITA, hh.MembershipRole.tenant, REAL_ROOM),
        (LANDLORD_REAL, hh.MembershipRole.landlord, None),
        (OPERATOR_REAL, hh.MembershipRole.operator, None),
    ):
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", f"real-{res}"),
                household_id=REAL_HOUSE,
                resident_id=res,
                role=role,
                room_id=room,
                starts_on=date(2026, 9, 1),
                status=hh.MembershipStatus.active,
            ),
        )


@pytest.fixture
def real_house(app):
    app.state.db.run_sync(seed_real_house)


@pytest.fixture
def register(app):
    """Regista um `ProviderSet` em `app.state` (como a composição de P4/P1) e limpa no fim."""

    def _register(registered) -> None:
        setattr(app.state, REGISTRY_ATTR, registered)

    yield _register
    if hasattr(app.state, REGISTRY_ATTR):
        delattr(app.state, REGISTRY_ATTR)


def ask(client, sub, text="Qual o meu consumo?", house=fx.HOUSEHOLD):
    return client.post(url(house), json={"text": text}, headers=as_(sub))


RITA_SUB = f"sub-{RITA}"
SENHORIO_SUB = f"sub-{LANDLORD_REAL}"
OPERADOR_SUB = f"sub-{OPERATOR_REAL}"


# --- HTTP: casa real -----------------------------------------------------------------------------


def test_provider_registado_serve_casa_real(client, real_house, register):
    fake = FakeReal(consumption=value())
    register(ProviderSet(consumption=fake))
    r = ask(client, RITA_SUB, house=REAL_HOUSE)
    assert r.status_code == 200
    body = r.json()
    assert format_kwh(4_321) in body["text"] and format_eur(1_234) in body["text"]
    assert body["tool_result_ids"] and "SIMULADO" not in body["text"]
    assert fake.calls == ["consumption"]


def test_casa_real_sem_provider_registado_nao_tem_dados(client, real_house):
    body = ask(client, RITA_SUB, house=REAL_HOUSE).json()
    assert "Não tenho dados" in body["text"] and body["tool_result_ids"] == []


def test_registo_lido_em_tempo_de_pedido(client, real_house, register):
    assert ask(client, RITA_SUB, house=REAL_HOUSE).json()["tool_result_ids"] == []
    register(ProviderSet(consumption=FakeReal(consumption=value())))  # depois do arranque
    assert ask(client, RITA_SUB, house=REAL_HOUSE).json()["tool_result_ids"]


def test_valores_simulados_numa_casa_real_sao_descartados(client, real_house, register):
    register(ProviderSet(consumption=FakeReal(consumption=value(SIM))))
    body = ask(client, RITA_SUB, house=REAL_HOUSE).json()
    assert "Não tenho dados" in body["text"] and body["tool_result_ids"] == []
    assert format_kwh(4_321) not in body["text"]


def test_casa_demo_marcada_real_descarta_os_simulados_do_provider(client, app, register):
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET source_kind = 'real' WHERE id = ?", (str(fx.HOUSEHOLD),)
        )
    )
    register(ProviderSet(consumption=FakeReal(consumption=value(SIM))))
    body = ask(client, "sub-ana").json()
    assert body["tool_result_ids"] == [] and "SIMULADO" not in body["text"]


@pytest.mark.parametrize("sub", [SENHORIO_SUB, OPERADOR_SUB])
def test_senhorio_e_operador_403_sem_chamar_providers(client, real_house, register, sub):
    fake = FakeReal(consumption=value())
    register(ProviderSet(consumption=fake, budget=fake, receipt=fake))
    r = ask(client, sub, house=REAL_HOUSE)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"
    assert fake.calls == []


def test_provider_que_levanta_da_200_sem_dados_e_sem_vazar(client, real_house, register, caplog):
    register(ProviderSet(consumption=FakeReal(error=RuntimeError("Bearer segredo-xyz"))))
    with caplog.at_level("WARNING"):
        r = ask(client, RITA_SUB, house=REAL_HOUSE)
    assert r.status_code == 200
    assert r.json()["tool_result_ids"] == [] and "segredo-xyz" not in r.text
    assert "RuntimeError" in caplog.text and "segredo-xyz" not in caplog.text


# --- HTTP: casa demo -----------------------------------------------------------------------------


def test_casa_demo_recua_para_simulado_quando_o_real_devolve_none(client, register):
    fake = FakeReal()  # tudo None
    register(ProviderSet(consumption=fake, budget=fake, receipt=fake))
    body = ask(client, "sub-ana").json()
    alloc = {a.resident_id: a for a in fx.bill_a()[1]}[fx.ANA]
    assert format_kwh(alloc.attributed_total_wh) in body["text"] and "SIMULADO" in body["text"]
    assert fake.calls == ["consumption"]  # o real foi tentado primeiro


def test_casa_demo_prefere_o_real_ao_simulado(client, register):
    register(ProviderSet(consumption=FakeReal(consumption=value())))
    body = ask(client, "sub-ana").json()
    assert format_kwh(4_321) in body["text"] and "SIMULADO" not in body["text"]


def test_demo_sem_registo_e_igual_ao_de_antes(client):
    alloc = {a.resident_id: a for a in fx.bill_a()[1]}[fx.ANA]
    body = ask(client, "sub-ana").json()
    assert format_kwh(alloc.attributed_total_wh) in body["text"] and "SIMULADO" in body["text"]


def test_llm_continua_a_usar_so_ferramentas(client, llm, register):
    register(ProviderSet(consumption=FakeReal(consumption=value())))
    llm.complete = FakeLLM(
        [
            '{"tools": [{"tool": "consumption_summary", "args": {}}]}',
        ]
    )
    body = ask(client, "sub-ana").json()
    assert format_kwh(4_321) in body["text"] and body["tool_result_ids"]


# --- unidade: cadeias ----------------------------------------------------------------------------


def test_ferramentas_sao_independentes():
    only_budget = FakeReal(budget=value(wh=None))
    reg = registry(ProviderSet(budget=only_budget), fx.HOUSEHOLD, "demo")
    ctx = ctx_for(fx.HOUSEHOLD, fx.CARLA)
    budget = reg.call("budget_status", {"period": fx.budget().period}, ctx)
    assert budget.result.cost_cents == 1_234 and not budget.result.provenance.simulated
    consumption = reg.call("consumption_summary", {}, ctx)  # sem registo → simulado
    assert consumption.result.provenance.simulated


def test_aparelhos_simulados_sao_descartados_em_casa_real():
    resolved = resolve(ProviderSet(appliances=FakeAppliances()), REAL_HOUSE, "real")
    assert resolved[3].top_appliances(REAL_HOUSE, RITA, PERIOD) is None


def test_excecao_nao_recua_para_o_simulado():
    reg = registry(ProviderSet(consumption=FakeReal(error=ValueError("x"))), fx.HOUSEHOLD, "demo")
    call = reg.call("consumption_summary", {}, ctx_for(fx.HOUSEHOLD, fx.ANA))
    assert call.result.error_code == "provider_error" and call.result.energy_wh is None


def test_excecao_no_latest_bill_e_provider_error():
    reg = registry(ProviderSet(receipt=FakeReal(error=ValueError("x"))), fx.HOUSEHOLD, "demo")
    call = reg.call("receipt", {}, ctx_for(fx.HOUSEHOLD, fx.ANA))
    assert call.result.error_code == "provider_error"


def test_simulado_numa_casa_real_e_no_data():
    reg = registry(ProviderSet(consumption=FakeReal(consumption=value(SIM))), REAL_HOUSE, "real")
    call = reg.call("consumption_summary", {}, ctx_for(REAL_HOUSE, RITA))
    assert call.result.error_code == "no_data" and call.result.energy_wh is None


def test_casa_real_nunca_usa_o_simulado_das_fixtures():
    reg = registry(ProviderSet(), fx.HOUSEHOLD, "real")  # id da demo, mas casa real
    call = reg.call("consumption_summary", {}, ctx_for(fx.HOUSEHOLD, fx.ANA))
    assert call.result.error_code == "no_data"


def test_outra_casa_demo_nao_recebe_as_fixtures():
    reg = registry(ProviderSet(), stable_id("household", "casa-b"), "demo")
    call = reg.call("consumption_summary", {}, ctx_for(stable_id("household", "casa-b"), fx.ANA))
    assert call.result.error_code == "no_data"


def test_recibo_real_usa_o_mesmo_provider_do_latest_bill():
    real = FakeReal(receipt=value(wh=None, cents=999), bill=(REAL_BILL, PERIOD))
    reg = registry(ProviderSet(receipt=real), REAL_HOUSE, "real")
    call = reg.call("receipt", {}, ctx_for(REAL_HOUSE, RITA))
    assert call.result.cost_cents == 999 and call.request.bill_id == REAL_BILL
    assert real.calls == ["latest_bill", "receipt"]


def test_recibo_do_simulado_nao_vai_ao_provider_real():
    # O real não tem recibo (latest_bill None): o recibo é o simulado e `receipt` não pergunta ao
    # real (que, se perguntado, responderia com um valor que não é daquela fatura).
    real = FakeReal(receipt=value(wh=None, cents=999), bill=None)
    reg = registry(ProviderSet(receipt=real), fx.HOUSEHOLD, "demo")
    call = reg.call("receipt", {}, ctx_for(fx.HOUSEHOLD, fx.ANA))
    alloc = {a.resident_id: a for a in fx.bill_a()[1]}[fx.ANA]
    assert call.request.bill_id == fx.BILL_A and call.result.cost_cents == alloc.amount_cents
    assert real.calls == ["latest_bill"]


def test_recibo_do_real_sem_valor_nao_cai_no_simulado():
    real = FakeReal(receipt=None, bill=(OTHER_BILL, PERIOD))
    reg = registry(ProviderSet(receipt=real), fx.HOUSEHOLD, "demo")
    call = reg.call("receipt", {}, ctx_for(fx.HOUSEHOLD, fx.ANA))
    assert call.result.error_code == "no_data" and call.request.bill_id == OTHER_BILL
    assert not call.result.provenance or not call.result.provenance.simulated


def test_receipt_de_fatura_desconhecida_tenta_os_elos_por_ordem():
    real = FakeReal(receipt=None)
    receipt = resolve(ProviderSet(receipt=real), fx.HOUSEHOLD, "demo")[2]
    got = receipt.receipt(fx.HOUSEHOLD, fx.ANA, fx.BILL_A)  # sem latest_bill antes
    assert got is not None and got.provenance.simulated and real.calls == ["receipt"]


def test_cadeia_de_recibo_nao_partilha_estado_entre_pedidos():
    registered = ProviderSet(receipt=FakeReal(receipt=value(), bill=(REAL_BILL, PERIOD)))
    a = resolve(registered, REAL_HOUSE, "real")[2]
    b = resolve(registered, REAL_HOUSE, "real")[2]
    assert a is not b


# --- registo ------------------------------------------------------------------------------------


def test_get_registered_sem_registo_ou_com_tipo_errado():
    def req(**state):
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))

    assert get_registered(req()) == ProviderSet()
    assert get_registered(req(agent_providers=object())) == ProviderSet()
    ps = ProviderSet(consumption=FakeReal())
    assert get_registered(req(agent_providers=ps)) is ps


def test_nome_do_registo():
    assert providers_mod.REGISTRY_ATTR == "agent_providers"


# --- isolamento entre features -------------------------------------------------------------------


def test_modulos_do_agente_nao_importam_outras_features_nem_connectors():
    pkg = Path(providers_mod.__file__).parent
    offenders = []
    for path in sorted(pkg.glob("*.py")):  # só código de produção; os testes podem semear a BD
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                base = node.module or ""
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            else:
                continue
            for n in names:
                parts = n.split(".")
                other_feature = parts[:2] == ["homemind", "features"] and (
                    len(parts) > 2 and parts[2] != "agent"
                )
                if other_feature or parts[:2] == ["homemind", "connectors"]:
                    offenders.append(f"{path.name}: {n}")
    assert not offenders, offenders
