"""Transporte OAuth do MCP: um pedido por chamada (bug do SDK 1.12.4 que reenvia sempre)."""

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from mcp.client.auth import OAuthClientMetadata
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken

from homemind.connectors.altice_auth import (
    JsonTokenStorage,
    OAuthReauthRequired,
    PersistentOAuthClientProvider,
)

URL = "http://mcp.test/mcp"
ISSUER = "http://auth.test"


def _provider(
    tmp_path: Path, *, token: OAuthToken, saved_at: float | None = None
) -> PersistentOAuthClientProvider:
    storage = JsonTokenStorage(tmp_path / "auth" / "tokens.json")
    storage.tokens = token
    storage.saved_at = saved_at if saved_at is not None else time.time()
    storage.client_info = OAuthClientInformationFull(
        client_id="c", redirect_uris=["http://localhost/cb"]
    )
    storage.oauth_metadata = OAuthMetadata(
        issuer=ISSUER,
        authorization_endpoint=f"{ISSUER}/auth",
        token_endpoint=f"{ISSUER}/token",
        response_types_supported=["code"],
    )

    async def redirect(_url: str) -> None:
        raise OAuthReauthRequired("login necessário")

    async def callback() -> tuple[str, str | None]:
        raise OAuthReauthRequired("login necessário")

    return PersistentOAuthClientProvider(
        server_url=URL,
        client_metadata=OAuthClientMetadata(redirect_uris=["http://localhost/cb"]),
        storage=storage,
        redirect_handler=redirect,
        callback_handler=callback,
    )


async def _post(provider: PersistentOAuthClientProvider, handler) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        await client.post(URL, json={"x": 1})


def test_valid_token_sends_exactly_one_request(tmp_path: Path) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("authorization")))
        return httpx.Response(200, json={"ok": True})

    prov = _provider(
        tmp_path, token=OAuthToken(access_token="A", token_type="bearer", expires_in=3600)
    )
    asyncio.run(_post(prov, handler))
    assert seen == [("POST", "/mcp", "Bearer A")]


def test_401_without_login_raises_reauth_without_extra_requests(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path))
        return httpx.Response(401 if req.url.path == "/mcp" else 404)

    prov = _provider(
        tmp_path, token=OAuthToken(access_token="A", token_type="bearer", expires_in=3600)
    )
    with pytest.raises(OAuthReauthRequired):
        asyncio.run(_post(prov, handler))
    assert seen.count(("POST", "/mcp")) == 1  # sem reenvio nem ciclo
    assert len(seen) < 10


def test_expired_token_refreshes_once_then_sends_with_new_token(tmp_path: Path) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("authorization")))
        if req.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "refresh_token": "R2",
                },
            )
        return httpx.Response(200, json={"ok": True})

    prov = _provider(
        tmp_path,
        token=OAuthToken(
            access_token="OLD", token_type="bearer", expires_in=60, refresh_token="R1"
        ),
        saved_at=time.time() - 10_000,
    )
    asyncio.run(_post(prov, handler))
    assert [(m, p) for m, p, _ in seen] == [("POST", "/token"), ("POST", "/mcp")]
    assert seen[1][2] == "Bearer NEW"


def test_doctor_prints_raw_plug_measures(capsys: pytest.CaptureFixture[str]) -> None:
    from homemind.connectors.altice_auth import _imprimir_medidas_tomada

    _imprimir_medidas_tomada(
        {
            "instantPower": {"type": "instantPower", "value": 550, "min": 0, "max": 3680},
            "instantVoltage": {"type": "instantVoltage", "value": 230, "unitOfMeasure": "V"},
        }
    )
    out = capsys.readouterr().out
    assert '"value": 550' in out and '"max": 3680' in out
    assert '"unitOfMeasure": "V"' in out
    assert "instantCurrent: não declarada" in out
