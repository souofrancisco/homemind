import pytest
from fastapi import APIRouter, FastAPI

from homemind.core import features
from homemind.core.features import discover_routers, register_features


def _router(path: str) -> APIRouter:
    r = APIRouter()
    r.add_api_route(path, lambda: None, methods=["GET"])
    return r


def test_discovery_is_sorted_and_finds_health():
    names = [n for n, _ in discover_routers()]
    assert names == sorted(names) and "health" in names


def test_duplicate_route_fails(monkeypatch):
    dup = [("a", _router("/x")), ("b", _router("/x"))]
    monkeypatch.setattr(features, "discover_routers", lambda: dup)
    with pytest.raises(RuntimeError, match="rota duplicada GET /x"):
        register_features(FastAPI())
