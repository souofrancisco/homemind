"""Guarda-corpos: números inventados e pedidos de ação. Lógica pura."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Espaço normal, NBSP e espaço fino como separadores de milhares ("1 234,56").
_SPACES = "   "
_NUMBER = re.compile(
    rf"(?<!\w)(?:\d{{1,3}}(?:\.\d{{3}})+,\d+|\d+(?:[{_SPACES}]\d{{3}}(?!\d))*(?:[.,]\d+)?)"
)
# Pedidos de ação (verbos de ligar/desligar/acender/apagar, mudar/pôr/colocar, brilho e cor) e os
# temas proibidos. Alargar isto só faz o pedido ser tratado como ação (proposta ou recusa), nunca
# executá-lo; um falso positivo dá uma recusa em vez de uma resposta de leitura.
_ACTION = re.compile(
    r"\b(desliga\w*|liga|ligar|ligues?|ligam|acende\w*|apaga\w*|alarme\w*|cenario\w*|seguranca"
    r"|mud(?:a|as|ar|e|es|em)|poes?|ponhas?|coloca\w*|brilho|intensidade|cor)\b"
)


def _to_decimal(raw: str) -> Decimal | None:
    s = re.sub(rf"[{_SPACES}]", "", raw)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:  # 1,234.56
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def extract_numbers(text: str) -> list[tuple[str, Decimal]]:
    """Números do texto como (texto original, valor). Vírgula ou ponto decimais, milhares."""
    found = []
    for m in _NUMBER.finditer(text):
        value = _to_decimal(m.group())
        if value is not None:
            found.append((m.group(), value))
    return found


def invented_numbers(text: str, allowed: frozenset[Decimal]) -> list[str]:
    """Números do texto que não estão em `allowed`. Os da pergunta do utilizador não contam."""
    return [raw for raw, value in extract_numbers(text) if value not in allowed]


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_action_request(text: str) -> bool:
    """Pedido para ligar/desligar, alarmes, cenários ou segurança (fora do âmbito de leitura)."""
    return _ACTION.search(plain(text)) is not None
