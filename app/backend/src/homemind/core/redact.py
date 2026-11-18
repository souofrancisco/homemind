"""Mascarar dados sensíveis nos logs (PRIV-04). Aplica-se a TODOS os registos do processo.

Instalado como *record factory* do `logging`: cada registo é mascarado ao nascer, antes de
qualquer handler (os da app, os do uvicorn, o `lastResort`). Mascara:

- segredos: `Bearer …`, `chave=valor`/`"chave": "valor"` para token, api_key, secret,
  password, authorization, cookie; `?code=`/`&state=` do OAuth; credenciais em URLs (`esquema://u:p@`);
- URLs RTSP inteiras (o URL da câmara é segredo);
- endereços MAC e emails;
- UUIDs: ficam os primeiros 8 caracteres (`1a2b3c4d…`), o bastante para correlacionar no log.

É uma rede de segurança, não licença para logar dados: o código continua a não os registar.
"""

import logging
import re

_SECRET_KEYS = (
    r"(?:access_token|refresh_token|id_token|token|api[_-]?key|x-api-key"
    r"|secret|password|passwd|authorization|cookie)"
)
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"rtsp://\S+", re.I), "rtsp://***"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 ***"),
    (re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1***@"),
    (
        re.compile(
            rf"""(?i)(["']?\b{_SECRET_KEYS}\b["']?\s*[:=]\s*["']?)(?!%[sdrf])[^\s"',&}}]+"""
        ),
        r"\1***",
    ),
    (re.compile(r"(?i)([?&](?:code|state)=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}\b"), "**:**:**:**:**:**"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "***@***"),
    (
        re.compile(
            r"\b([0-9a-fA-F]{8})-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        r"\1…",
    ),
)


def redact(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


def _arg(value: object) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact(str(value))


def _mask(record: logging.LogRecord) -> None:
    """Primeiro argumento a argumento (formatadores como o de acesso do uvicorn leem
    `record.args` como tuplo); se a mensagem final ainda tiver algo a mascarar (ex.: o segredo
    é um argumento sozinho em `"token=%s"`), fica só a mensagem final mascarada."""
    full = record.getMessage()
    masked = redact(full)
    if masked == full:
        return
    msg = redact(record.msg) if isinstance(record.msg, str) else redact(str(record.msg))
    if isinstance(record.args, tuple):
        new_args: object = tuple(_arg(a) for a in record.args)
    elif isinstance(record.args, dict):
        new_args = {k: _arg(v) for k, v in record.args.items()}
    else:
        new_args = record.args
    try:
        candidate = msg % new_args if new_args else msg
    except (TypeError, ValueError, KeyError):
        candidate = None
    if candidate is not None and redact(candidate) == candidate:
        record.msg, record.args = msg, new_args
    elif record.name.startswith("uvicorn.access"):
        record.msg, record.args = msg, new_args  # o formatador exige o tuplo
    else:
        record.msg, record.args = masked, ()


_installed = False


def install_log_redaction() -> None:
    """Idempotente. A mensagem final (com os argumentos) e o traceback são mascarados."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        try:
            _mask(record)
            if record.exc_info and not record.exc_text:
                record.exc_text = redact(formatter.formatException(record.exc_info))
        except Exception:  # um log nunca pode rebentar; na dúvida, não sai nada do conteúdo
            record.msg, record.args = "[mensagem omitida: falha ao mascarar]", ()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
