"""Descoberta automática: cada `features/<nome>/router.py` expõe `router` (APIRouter)."""

import importlib
import pkgutil

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from homemind import features


def discover_routers() -> list[tuple[str, APIRouter]]:
    """Routers das features, por ordem alfabética (determinística)."""
    found = []
    for info in sorted(pkgutil.iter_modules(features.__path__), key=lambda i: i.name):
        if not info.ispkg:
            continue
        mod_name = f"{features.__name__}.{info.name}.router"
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as e:
            if e.name == mod_name:  # feature sem router: ignorar; outros erros propagam
                continue
            raise
        found.append((info.name, mod.router))
    return found


def register_features(app: FastAPI) -> None:
    seen: dict[tuple[str, str], str] = {}
    for name, router in discover_routers():
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods:
                key = (method, route.path)
                if key in seen:
                    raise RuntimeError(
                        f"rota duplicada {method} {route.path}: features '{seen[key]}' e '{name}'"
                    )
                seen[key] = name
        app.include_router(router)
