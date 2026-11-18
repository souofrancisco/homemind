"""Formatação de texto para o utilizador (PT-PT)."""


def format_eur(cents: int) -> str:
    """Cêntimos inteiros em euros, em PT-PT: `64` -> `0,64 €`, `123456` -> `1 234,56 €`.

    Só aritmética inteira (nunca `float`).
    """
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    grouped = f"{euros:,}".replace(",", " ")
    return f"{sign}{grouped},{rest:02d} €"


def format_kw(watts: float) -> str:
    """Potência em kW com uma casa decimal, em PT-PT: `2040.0` -> `2,0 kW`."""
    return f"{watts / 1000:.1f} kW".replace(".", ",")


def format_kwh(wh: int) -> str:
    """Energia em kWh com uma casa decimal, em PT-PT: `5400` -> `5,4 kWh`."""
    return f"{wh / 1000:.1f} kWh".replace(".", ",")
