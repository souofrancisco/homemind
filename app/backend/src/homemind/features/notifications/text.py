"""Formatação de texto para o utilizador (PT-PT)."""


def format_eur(cents: int) -> str:
    """Cêntimos inteiros em euros, em PT-PT: `64` -> `0,64 €`, `123456` -> `1 234,56 €`.

    Só aritmética inteira (nunca `float`).
    """
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    grouped = f"{euros:,}".replace(",", " ")
    return f"{sign}{grouped},{rest:02d} €"
