import pytest

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.features.agent.formatting import (
    format_eur,
    format_kwh,
    format_period,
    provenance_label,
)
from homemind.features.agent.tests._fakes import SIMULATED_INFERRED


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
