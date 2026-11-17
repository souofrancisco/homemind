"""Inclui no OpenAPI os modelos partilhados que o frontend precisa e que nenhuma rota usa ainda.

Sem rotas falsas: `app.openapi()` (e por isso `/openapi.json` e `make contracts`) junta ao
`components.schemas` os modelos de `contracts.api.OPENAPI_MODELS`. Um modelo já gerado pelo
FastAPI (usado por uma rota real) mantém-se como está.
"""

from fastapi import FastAPI
from pydantic.json_schema import models_json_schema

from homemind.contracts.api import OPENAPI_MODELS


def install_shared_schemas(app: FastAPI) -> None:
    original = app.openapi

    def openapi() -> dict:
        schema = original()
        _, defs = models_json_schema(
            [(m, "serialization") for m in OPENAPI_MODELS],
            ref_template="#/components/schemas/{model}",
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in defs.get("$defs", {}).items():
            components.setdefault(name, definition)
        return schema

    app.openapi = openapi
