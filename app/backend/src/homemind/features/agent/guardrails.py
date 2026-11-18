"""Guarda-corpos: números inventados e pedidos de ação. Lógica pura."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Espaço normal, NBSP e espaço fino como separadores de milhares ("1 234,56").
_SPACES = "   "
_NUMBER = re.compile(
    rf"(?<!\w)(?:\d{{1,3}}(?:\.\d{{3}})+,\d+|\d+(?:[{_SPACES}]\d{{3}}(?!\d))*(?:[.,]\d+)?)"
)
# Pedidos de ação. Só imperativo, infinitivo e 2.ª pessoa («desliga», «desligar», «desligue»):
# NUNCA particípios («desligada», «apagada», «ligada»), que descrevem estado e não pedem nada.
# Alargar isto só faz o pedido ser tratado como ação (proposta ou recusa), nunca executá-lo; um
# falso positivo dá uma recusa em vez de uma resposta de leitura, por isso o gatilho é estreito.
OFF_VERBS = (
    r"desliga|desligar|desligue|desligues|desliguem|desligas|apaga|apagar|apague|apagues|apaguem"
    r"|apagas"
)
ON_VERBS = (
    r"liga|ligar|ligue|ligues|liguem|ligas|ligam|acende|acender|acenda|acendas|acendam|acendes"
)
_POWER = re.compile(rf"\b(?:{OFF_VERBS}|{ON_VERBS})\b")
# Alarmes, cenários e segurança: continuam a ser recusados, mesmo numa pergunta.
_FORBIDDEN_TOPIC = re.compile(r"\b(alarme\w*|cenario\w*|seguranca)\b")
# Mudar/pôr/colocar só pedem uma ação se houver um dispositivo («põe-me o consumo de novembro»
# é uma pergunta de leitura).
_CHANGE = re.compile(r"\b(mud(?:a|as|ar|e|es|em)|poes?|ponhas?|colocar?|colocas?|coloque)\b")
_DEVICE_NOUN = re.compile(
    r"\b(luz|luzes|lampadas?|candeeiros?|iluminacao|tomadas?|extensao|extensoes|aquecedor\w*"
    r"|ficha|regua)\b"
)
_BRIGHTNESS_NOUN = re.compile(r"\b(brilho|intensidade)\b")
_HAS_NUMBER = re.compile(r"\d")
# Pergunta de leitura: começa por uma palavra interrogativa, ou acaba em «?» (a menos que seja um
# pedido cortês: «podes desligar a luz?»).
_QUESTION_START = re.compile(
    r"^\W*(?:quanto|quanta|quantos|quantas|qual|quais|o que|esta|estao|como|quando|porque"
    r"|por que|onde|quem)\b"
)
_POLITE = re.compile(
    r"^\W*(?:podes|pode|poderias|podias|consegues|queres|importas|faz favor|fazes favor)\b"
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


def is_question(text: str) -> bool:
    """Pergunta de leitura (nunca um pedido de ação). Recebe o texto já passado por `plain`."""
    t = text.strip()
    if _QUESTION_START.search(t):
        return True
    return t.endswith("?") and not _POLITE.search(t)


def is_action_request(text: str) -> bool:
    """Pedido para ligar/desligar/mudar um dispositivo, ou tema proibido (alarmes, cenários,
    segurança). Uma pergunta de leitura nunca é um pedido de ação."""
    t = plain(text)
    if _FORBIDDEN_TOPIC.search(t):
        return True
    if is_question(t):
        return False
    if _POWER.search(t):
        return True
    device, brightness = _DEVICE_NOUN.search(t), _BRIGHTNESS_NOUN.search(t)
    number = _HAS_NUMBER.search(t)
    if _CHANGE.search(t):
        return bool(device or (brightness and number))
    return bool(device and brightness and number)  # «brilho da luz a 100%»
