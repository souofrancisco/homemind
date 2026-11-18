"""PRIV-04: os logs nunca levam segredos, URL RTSP, MAC, emails nem ids completos."""

import logging

import pytest

from homemind.core.redact import install_log_redaction, redact

UUID_ = "1a2b3c4d-1111-2222-3333-444455556666"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Authorization: Bearer eyJhbGciOi.abc-123", "Authorization: *** ***"),
        ("pedido com bearer abc.def", "pedido com bearer ***"),
        ("X-API-Key: sk_live_123", "X-API-Key: ***"),
        (
            '{"access_token": "tok123", "expires_in": 3600}',
            '{"access_token": "***", "expires_in": 3600}',
        ),
        ("api_key=abc&x=1", "api_key=***&x=1"),
        ("callback /cb?code=XYZ&state=s1 ok", "callback /cb?code=***&state=*** ok"),
        ("câmara rtsp://admin:pw@10.0.0.2:554/stream1 caiu", "câmara rtsp://*** caiu"),
        ("https://user:pass@example.org/x", "https://***@example.org/x"),
        ("telemóvel AA:bb:0c:11:22:33 visto", "telemóvel **:**:**:**:**:** visto"),
        ("mac aa-bb-cc-dd-ee-ff", "mac **:**:**:**:**:**"),
        ("enviado para ana.silva@example.pt", "enviado para ***@***"),
        (f"casa {UUID_}", "casa 1a2b3c4d…"),
        (
            "leitura 1500 W às 19:00:05, status code: 404",
            "leitura 1500 W às 19:00:05, status code: 404",
        ),
    ],
)
def test_redact(raw, expected):
    assert redact(raw) == expected


@pytest.fixture
def captured():
    install_log_redaction()
    install_log_redaction()  # idempotente
    records: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record):
            records.append(record)

    log = logging.getLogger("homemind.test.redact")
    handler = Keep()
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    yield log, records
    log.removeHandler(handler)


def test_argumentos_e_mensagem_final_sao_mascarados(captured):
    log, records = captured
    log.info("casa %s com %d tomadas", UUID_, 3)
    log.warning("token=%s", "segredo-solto")  # o segredo é só um argumento
    log.info("sem nada %s", "para mascarar")
    assert [r.getMessage() for r in records] == [
        "casa 1a2b3c4d… com 3 tomadas",
        "token=***",
        "sem nada para mascarar",
    ]


def test_traceback_tambem_e_mascarado(captured):
    log, records = captured
    try:
        raise RuntimeError("falhou rtsp://u:p@cam/1")
    except RuntimeError:
        log.exception("erro")
    [r] = records
    assert "rtsp://***" in r.exc_text and "u:p@" not in r.exc_text


def test_acesso_do_uvicorn_continua_com_tuplo():
    """O formatador de acesso do uvicorn desempacota `record.args` (5 campos)."""
    install_log_redaction()
    record = logging.getLogRecordFactory()(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5", "GET", f"/api/households/{UUID_}/bills?code=abc", "1.1", 200),
        None,
    )
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert record.getMessage() == (
        '127.0.0.1:5 - "GET /api/households/1a2b3c4d…/bills?code=*** HTTP/1.1" 200'
    )
