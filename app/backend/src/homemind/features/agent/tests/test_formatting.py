from decimal import Decimal
from uuid import uuid4

import pytest

from homemind.contracts.agent import AgentTool, AgentToolRequest, AgentToolResult
from homemind.contracts.common import OperationStatus, Origin, Provenance, ValueKind
from homemind.features.agent.formatting import (
    Fact,
    allowed_numbers,
    fact_from,
    format_eur,
    format_kwh,
    format_period,
    provenance_label,
    render_fact,
)
from homemind.features.agent.tests._fakes import (
    SIMULATED_INFERRED,
    SIMULATED_MEASURED,
)


@pytest.mark.parametrize(
    ("cents", "text"),
    [(0, "0,00 €"), (64, "0,64 €"), (2_000, "20,00 €"), (123_456, "1 234,56 €")],
)
def test_format_eur(cents, text):
    assert format_eur(cents) == text


@pytest.mark.parametrize(
    ("wh", "text"),
    [
        (0, "0,0 kWh"),
        (12_340, "12,3 kWh"),
        (12_350, "12,4 kWh"),
        (12_250, "12,2 kWh"),
        (1_234_500, "1 234,5 kWh"),
    ],
)
def test_format_kwh_arredonda_ao_par(wh, text):
    assert format_kwh(wh) == text


def test_format_period():
    assert format_period("2026-11") == "novembro de 2026"
    assert format_period("2026-03") == "março de 2026"
    with pytest.raises(ValueError):
        format_period("2026-13")


def test_provenance_label():
    assert provenance_label(Provenance(origin=Origin.real, kind=ValueKind.measured)) == (
        "medido · REAL"
    )
    assert provenance_label(SIMULATED_INFERRED) == "inferido (com incerteza) · SIMULADO"


def _result(**kw):
    base = {
        "request_id": uuid4(),
        "tool": AgentTool.consumption_summary,
        "status": OperationStatus.succeeded,
        "provenance": SIMULATED_INFERRED,
        "energy_wh": 12_340,
        "cost_cents": 2_345,
    }
    return AgentToolResult(**(base | kw))


def test_fact_from_e_render():
    res = _result()
    fact = fact_from(None, res, "2026-11")
    assert fact is not None and fact.result_id == res.request_id
    assert fact.values == {"energia": "12,3 kWh", "custo": "23,45 €"}
    text = render_fact(fact)
    assert "novembro de 2026" in text and "inferido (com incerteza) · SIMULADO" in text
    assert "12,3 kWh" in text and "23,45 €" in text


def test_fact_from_sem_valores_ou_falha():
    failed = AgentToolResult(
        request_id=uuid4(),
        tool=AgentTool.budget_status,
        status=OperationStatus.failed,
        error_code="no_data",
    )
    assert fact_from(None, failed, "2026-11") is None
    assert (
        fact_from(None, _result(energy_wh=None, cost_cents=None, provenance=None), "2026-11")
        is None
    )


def test_fact_from_rejeita_pedido_de_outro_resultado():
    res = _result()
    req = AgentToolRequest(id=uuid4(), tool=AgentTool.consumption_summary, period="2026-11")
    assert fact_from(req, res, "2026-11") is None
    ok = AgentToolRequest(id=res.request_id, tool=AgentTool.consumption_summary, period="2026-11")
    assert fact_from(ok, res, "2026-11") is not None


def test_allowed_numbers_inclui_valores_e_ano():
    fact = Fact(
        AgentTool.budget_status,
        "novembro de 2026",
        "medido · SIMULADO",
        {"gasto": "64,00 €", "energia": "1 234,5 kWh"},
        uuid4(),
    )
    allowed = allowed_numbers([fact])
    assert {Decimal("64"), Decimal("1234.5"), Decimal("2026")} <= allowed
    assert Decimal("80") not in allowed
    assert SIMULATED_MEASURED  # fixture importada
