import logging
from itertools import count
from uuid import UUID

import pytest

from homemind.contracts.agent import AgentTool, AgentToolResult
from homemind.contracts.common import OperationStatus
from homemind.features.agent.tests._fakes import (
    BILL,
    EmptyBudget,
    EmptyConsumption,
    EmptyReceipt,
    FakeBudget,
    FakeConsumption,
    FakeReceipt,
    SpyProvider,
    ctx,
)
from homemind.features.agent.tools import ToolRegistry, ToolRejected


def _registry(c=None, b=None, r=None):
    ids = count(1)
    return ToolRegistry(
        c or FakeConsumption(),
        b or FakeBudget(),
        r or FakeReceipt(),
        new_id=lambda: UUID(int=next(ids)),
    )


class Attribution:
    def explain_attribution(self, household_id, resident_id, period):
        from homemind.contracts.agent_providers import (
            AttributionPartValue,
            AttributionValue,
            ToolValue,
        )
        from homemind.features.agent.tests._fakes import SIMULATED_ESTIMATED

        return AttributionValue(
            ToolValue(None, 640, SIMULATED_ESTIMATED),
            (AttributionPartValue("O teu quarto", 640, SIMULATED_ESTIMATED),),
            False,
        )


class Confirmations:
    def pending_confirmations(self, household_id, resident_id):
        from datetime import datetime, timedelta

        from homemind.contracts.agent_providers import (
            ConfirmationsValue,
            ConfirmationValue,
        )
        from homemind.features.agent.tests._fakes import SIMULATED_ESTIMATED

        item = ConfirmationValue(
            "Aquecedor do Bruno",
            64,
            datetime.now().astimezone() + timedelta(hours=1),
            SIMULATED_ESTIMATED,
        )
        return ConfirmationsValue(4, (item, item, item))


def test_specs_so_de_leitura():
    assert {s.tool for s in _registry().specs()} == set(AgentTool)


def test_ferramenta_desconhecida():
    with pytest.raises(ToolRejected) as e:
        _registry().call("desligar_tomada", {}, ctx())
    assert e.value.code == "unknown_tool"


def test_resident_id_nos_argumentos_e_rejeitado():
    spy = SpyProvider()
    with pytest.raises(ToolRejected) as e:
        _registry(spy, spy, spy).call(
            "consumption_summary", {"period": "2026-11", "resident_id": "x"}, ctx()
        )
    assert e.value.code == "invalid_arguments" and spy.calls == 0


def test_bill_id_nos_argumentos_do_recibo_e_rejeitado():
    with pytest.raises(ToolRejected) as e:
        _registry().call("receipt", {"bill_id": str(BILL)}, ctx())
    assert e.value.code == "invalid_arguments"


@pytest.mark.parametrize("period", ["2026-13", "novembro", 202611, ["2026-11"]])
def test_periodo_invalido(period):
    with pytest.raises(ToolRejected) as e:
        _registry().call("budget_status", {"period": period}, ctx())
    assert e.value.code == "invalid_arguments"


def test_argumentos_nao_objeto():
    with pytest.raises(ToolRejected):
        _registry().call("budget_status", "2026-11", ctx())  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ["landlord", "operator"])
@pytest.mark.parametrize("name", ["consumption_summary", "budget_status", "receipt"])
def test_so_inquilinos_sem_chamar_fornecedores(role, name):
    spy = SpyProvider()
    call = _registry(spy, spy, spy).call(name, {}, ctx(role))
    assert call.result.status is OperationStatus.failed
    assert call.result.error_code == "forbidden_role"
    assert spy.calls == 0


def test_sem_dados():
    r = _registry(EmptyConsumption(), EmptyBudget(), EmptyReceipt())
    for name in ("consumption_summary", "budget_status", "receipt"):
        res = r.call(name, {}, ctx()).result
        assert res.status is OperationStatus.failed and res.error_code == "no_data"
    assert _registry().call("budget_status", {"period": "2026-10"}, ctx()).result.error_code == (
        "no_data"
    )


def test_excecao_do_fornecedor_nao_vaza(caplog):
    spy = SpyProvider(error=RuntimeError("segredo-do-fornecedor"))
    with caplog.at_level(logging.DEBUG):
        call = _registry(spy, spy, spy).call("consumption_summary", {}, ctx())
    assert call.result.error_code == "provider_error"
    assert "segredo-do-fornecedor" not in caplog.text
    assert "segredo-do-fornecedor" not in call.result.model_dump_json()
    assert "RuntimeError" in caplog.text


def test_sucesso_valida_como_resultado():
    r = _registry()
    cons = r.call("consumption_summary", {}, ctx())
    assert cons.period == "2026-11" and cons.request is not None
    assert cons.request.period == "2026-11" and cons.request.bill_id is None
    assert cons.result.request_id == cons.request.id
    AgentToolResult.model_validate(cons.result.model_dump())
    assert cons.result.energy_wh == 12_340 and cons.result.provenance.simulated

    bud = r.call("budget_status", {"period": "2026-11"}, ctx())
    assert bud.result.cost_cents == 6_400 and bud.result.energy_wh is None

    rec = r.call("receipt", {}, ctx())
    assert rec.request is not None and rec.request.bill_id == BILL and rec.request.period is None
    assert rec.result.cost_cents == 18_750 and rec.period == "2026-11"


def test_ferramentas_novas_tipadas_e_com_argumentos_validos():
    r = ToolRegistry(
        FakeConsumption(),
        FakeBudget(),
        FakeReceipt(),
        attribution=Attribution(),
        confirmations=Confirmations(),
    )
    explain = r.call("explain_attribution", {}, ctx())
    assert explain.result.cost_cents == 640 and explain.result.final is False
    assert explain.result.attribution_parts[0].amount_cents == 640
    pending = r.call("pending_confirmations", {}, ctx())
    assert pending.request.period is None
    assert pending.result.pending_count == 4 and len(pending.result.pending) == 3
    with pytest.raises(ToolRejected):
        r.call("pending_confirmations", {"period": "2026-11"}, ctx())


def test_senhorio_nao_consulta_novas_ferramentas():
    spy = SpyProvider()
    r = ToolRegistry(spy, spy, spy, attribution=spy, confirmations=spy)
    for name in ("explain_attribution", "pending_confirmations"):
        result = r.call(name, {}, ctx("landlord"))
        assert result.result.error_code == "forbidden_role"
    assert spy.calls == 0
