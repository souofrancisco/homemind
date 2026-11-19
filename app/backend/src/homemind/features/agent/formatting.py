"""Formatação PT-PT determinística de valores e proveniência para as respostas do agente."""

import re
from decimal import ROUND_HALF_EVEN, Decimal

from homemind.contracts.common import Provenance, ValueKind

_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_KIND = {
    ValueKind.measured: "medido",
    ValueKind.estimated: "estimado",
    ValueKind.inferred: "inferido (com incerteza)",
}


def format_eur(cents: int) -> str:
    """Cêntimos inteiros → «0,64 €», «1 234,56 €». Aritmética inteira."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", " ") + f",{rest:02d} €"


def format_kwh(wh: int) -> str:
    """Wh → «12,3 kWh» (1 casa, arredondamento ao par)."""
    kwh = (Decimal(wh) / Decimal(1000)).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    text = f"{kwh:,.1f}".replace(",", " ").replace(".", ",")
    return f"{text} kWh"


def format_period(period: str) -> str:
    """«2026-11» → «novembro de 2026»."""
    match = _PERIOD.match(period)
    if match is None:
        raise ValueError("período inválido")
    return f"{_MONTHS[int(match.group(2)) - 1]} de {match.group(1)}"


def provenance_label(provenance: Provenance) -> str:
    """«medido · REAL», «inferido (com incerteza) · SIMULADO»."""
    origin = "SIMULADO" if provenance.simulated else "REAL"
    return f"{_KIND[provenance.kind]} · {origin}"
