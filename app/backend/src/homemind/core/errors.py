"""Erros sempre como {"error": {"code", "message"}}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_errors(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, e: HTTPException) -> JSONResponse:
        # detail pode ser {"code", "message"} para um código específico; senão `http_<status>`.
        if isinstance(e.detail, dict) and {"code", "message"} <= e.detail.keys():
            body = _body(str(e.detail["code"]), str(e.detail["message"]))
        else:
            body = _body(f"http_{e.status_code}", str(e.detail))
        return JSONResponse(body, e.status_code, e.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
        # Só os campos em falta/errados (nunca os valores recebidos): ajuda a corrigir o pedido.
        campos = ", ".join(sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()}))
        mensagem = f"Pedido inválido ({campos})" if campos else "Pedido inválido"
        return JSONResponse(_body("invalid_request", mensagem[:300]), 400)

    @app.exception_handler(Exception)
    async def erro_interno(_: Request, e: Exception) -> JSONResponse:
        # Sem detalhes na resposta (podem conter URLs/credenciais); só o tipo fica no log.
        log.error("erro interno não tratado (%s)", type(e).__name__)
        return JSONResponse(_body("internal_error", "Erro interno"), 500)
