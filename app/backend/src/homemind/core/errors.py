"""Erros sempre como {"error": {"code", "message"}}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_errors(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, e: HTTPException) -> JSONResponse:
        return JSONResponse(_body(f"http_{e.status_code}", str(e.detail)), e.status_code, e.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
        return JSONResponse(_body("invalid_request", "Pedido inválido"), 400)
