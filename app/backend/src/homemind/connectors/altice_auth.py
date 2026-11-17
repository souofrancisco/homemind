"""OAuth 2.0 Authorization Code + PKCE para o MCP Altice (mcp==1.12.4)."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import re
import tempfile
import time
import webbrowser
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthClientProvider
from mcp.client.streamable_http import MCP_PROTOCOL_VERSION, streamablehttp_client
from mcp.shared.auth import OAuthMetadata, OAuthToken, ProtectedResourceMetadata
from mcp.types import LATEST_PROTOCOL_VERSION
from pydantic import ValidationError

from homemind.core.config import get_settings

log = logging.getLogger(__name__)


class OAuthCallbackError(RuntimeError):
    """OAuth server error code safe to report without response descriptions or secrets."""


class OAuthReauthRequired(RuntimeError):
    """Refresh token expirado/revogado: só `make mcp-login` no host recupera."""


def needs_login(exc: BaseException) -> bool:
    """True se `exc` (ou um filho de um ExceptionGroup) pede novo login."""
    if isinstance(exc, OAuthReauthRequired):
        return True
    return isinstance(exc, BaseExceptionGroup) and any(needs_login(e) for e in exc.exceptions)


class JsonTokenStorage:
    """Persist OAuth tokens and the fixed client registration in a mode-0600 file.

    O ficheiro vive numa diretoria própria (0700) para o `os.replace` atómico funcionar com
    bind mounts Docker. `flock` num ficheiro de lock coordena processos (host e container).
    """

    def __init__(self, path: Path):
        self.path = path
        self._mtime: float | None = None
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None
        self.oauth_metadata: OAuthMetadata | None = None
        self.protected_resource_metadata: ProtectedResourceMetadata | None = None
        self.saved_at: float | None = None
        self._load()

    @contextmanager
    def _flock(self) -> Iterator[None]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.path.parent / ".tokens.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self) -> None:
        path = self.path
        if path.is_file():
            try:
                self._mtime = path.stat().st_mtime
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.tokens = OAuthToken.model_validate(saved["tokens"])
                self.client_info = OAuthClientInformationFull.model_validate(saved["client_info"])
                if saved.get("oauth_metadata"):
                    self.oauth_metadata = OAuthMetadata.model_validate(saved["oauth_metadata"])
                if saved.get("protected_resource_metadata"):
                    self.protected_resource_metadata = ProtectedResourceMetadata.model_validate(
                        saved["protected_resource_metadata"]
                    )
                self.saved_at = float(saved.get("saved_at", 0)) or None
            except (OSError, KeyError, ValueError, TypeError) as exc:
                raise RuntimeError(
                    "Ficheiro de sessão MCP inválido; execute make mcp-login"
                ) from exc

    def _reload_if_changed(self) -> None:
        """Outro processo (ex.: `make mcp-login`) pode ter renovado os tokens entretanto."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return
        if mtime != self._mtime:
            with self._flock():
                self._load()

    async def get_tokens(self) -> OAuthToken | None:
        self._reload_if_changed()
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens
        self.saved_at = time.time()
        self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info
        self._save()

    def _save(self) -> None:
        if self.tokens is None or self.client_info is None:
            return
        payload = {
            "tokens": self.tokens.model_dump(mode="json", exclude_none=True),
            "client_info": self.client_info.model_dump(mode="json", exclude_none=True),
            "oauth_metadata": (
                self.oauth_metadata.model_dump(mode="json", exclude_none=True)
                if self.oauth_metadata
                else None
            ),
            "protected_resource_metadata": (
                self.protected_resource_metadata.model_dump(mode="json", exclude_none=True)
                if self.protected_resource_metadata
                else None
            ),
            "saved_at": self.saved_at,
        }
        with self._flock():
            fd, temp_path = tempfile.mkstemp(prefix=".mcp-tokens-", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(payload, file)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temp_path, self.path)
                self._mtime = self.path.stat().st_mtime
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)


class PersistentOAuthClientProvider(OAuthClientProvider):
    """Restore SDK expiry accounting so persisted tokens refresh after a restart."""

    async def _initialize(self) -> None:
        await super()._initialize()
        storage = self.context.storage
        if isinstance(storage, JsonTokenStorage):
            self.context.oauth_metadata = storage.oauth_metadata
            self.context.protected_resource_metadata = storage.protected_resource_metadata
            if storage.oauth_metadata:
                self.context.auth_server_url = str(storage.oauth_metadata.issuer)
            if self.context.current_tokens:
                expires_in = self.context.current_tokens.expires_in
                if expires_in is not None and storage.saved_at is not None:
                    # Refresh slightly early to avoid using a token at its expiry boundary.
                    self.context.token_expiry_time = storage.saved_at + max(expires_in - 30, 0)

    async def _handle_protected_resource_response(self, response: Any) -> None:
        await super()._handle_protected_resource_response(response)
        storage = self.context.storage
        if isinstance(storage, JsonTokenStorage):
            storage.protected_resource_metadata = self.context.protected_resource_metadata
            storage._save()

    async def _handle_oauth_metadata_response(self, response: Any) -> None:
        await super()._handle_oauth_metadata_response(response)
        storage = self.context.storage
        if isinstance(storage, JsonTokenStorage):
            storage.oauth_metadata = self.context.oauth_metadata
            storage._save()

    async def _handle_refresh_response(self, response: httpx.Response) -> bool:
        if response.status_code != 200:
            return await super()._handle_refresh_response(response)
        try:
            tokens = OAuthToken.model_validate_json(await response.aread())
            if tokens.refresh_token is None and self.context.current_tokens:
                # OAuth servers may keep the existing refresh token instead of rotating it.
                tokens.refresh_token = self.context.current_tokens.refresh_token
            self.context.current_tokens = tokens
            self.context.update_token_expiry(tokens)
            if tokens.expires_in:
                self.context.token_expiry_time = time.time() + max(tokens.expires_in - 30, 0)
            await self.context.storage.set_tokens(tokens)
            return True
        except ValidationError:
            log.warning("resposta de renovação OAuth inválida")
            self.context.clear_tokens()
            return False


async def _listener(
    callback_url: str, port: int
) -> tuple[asyncio.AbstractServer, asyncio.Future[tuple[str, str | None]]]:
    parsed_callback = urlparse(callback_url)
    if parsed_callback.port != port or not parsed_callback.path:
        raise RuntimeError(
            "MCP_OAUTH_CALLBACK_URL tem de corresponder à porta e ao caminho configurados"
        )
    loop = asyncio.get_running_loop()
    result: asyncio.Future[tuple[str, str | None]] = loop.create_future()

    async def receive(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1")
            parts = request_line.split()
            headers: dict[str, str] = {}
            while line := await asyncio.wait_for(reader.readline(), 10):
                if line in (b"\r\n", b"\n"):
                    break
                key, _, value = line.decode("latin-1").partition(":")
                headers[key.lower()] = value.strip()
            if len(parts) < 2 or parts[0] != "GET":
                status, message = "400 Bad Request", "Pedido de callback inválido."
            else:
                callback = urlparse(parts[1])
                query = parse_qs(callback.query)
                if callback.path != parsed_callback.path:
                    status, message = "404 Not Found", "Callback não encontrado."
                elif query.get("error"):
                    error_code = query["error"][0]
                    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", error_code):
                        error_code = "unknown"
                    if not result.done():
                        result.set_exception(OAuthCallbackError(error_code))
                    status, message = (
                        "400 Bad Request",
                        "A autorização foi recusada. Pode fechar esta página.",
                    )
                elif query.get("code"):
                    if not result.done():
                        result.set_result((query["code"][0], query.get("state", [None])[0]))
                    status, message = "200 OK", "Autenticação recebida. Pode regressar ao terminal."
                else:
                    status, message = "400 Bad Request", "Callback sem código de autorização."
            body = (
                "<!doctype html><meta charset='utf-8'><title>ObjectOS</title>" f"<p>{message}</p>"
            ).encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (OSError, TimeoutError, UnicodeDecodeError):
            if not result.done():
                result.set_exception(RuntimeError("Falha ao receber callback OAuth"))
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(receive, host="127.0.0.1", port=port)
    return server, result


def create_oauth_provider(
    *, interactive: bool = False
) -> tuple[PersistentOAuthClientProvider, JsonTokenStorage]:
    settings = get_settings()
    if not settings.mcp_endpoint or not settings.mcp_api_key:
        raise RuntimeError("MCP_ENDPOINT e MCP_API_KEY têm de estar configurados em app/.env")
    storage = JsonTokenStorage(settings.mcp_token_path)
    callback_server: asyncio.AbstractServer | None = None
    callback_result: asyncio.Future[tuple[str, str | None]] | None = None

    async def redirect_handler(url: str) -> None:
        nonlocal callback_server, callback_result
        if not interactive:
            raise OAuthReauthRequired(
                "Sessão MCP expirada; execute make mcp-login no host para autenticar novamente"
            )
        callback_server, callback_result = await _listener(
            settings.mcp_oauth_callback_url, settings.mcp_oauth_callback_port
        )
        if not webbrowser.open(url, new=2, autoraise=True):
            print("Não foi possível abrir o browser automaticamente. URL de autorização:")
            print(url)
            print("Conclua o login no browser e aguarde o callback.")

    async def callback_handler() -> tuple[str, str | None]:
        if not interactive:
            raise OAuthReauthRequired(
                "Sessão MCP expirada; execute make mcp-login no host para autenticar novamente"
            )
        if callback_server is None or callback_result is None:
            raise RuntimeError("Listener de callback OAuth não iniciado")
        try:
            return await callback_result
        finally:
            callback_server.close()
            await callback_server.wait_closed()

    redirect_uri = settings.mcp_oauth_callback_url
    metadata = OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        # Codex sends no scope. An explicit empty value prevents SDK 1.12.4 from
        # requesting every scope exposed by Keycloak's discovery document.
        scope="",
        client_name="ObjectOS",
    )
    # MCP 1.12.4 skips dynamic registration whenever storage has client_info.
    # This fixed client_id is the one registered with Altice/Codex configuration.
    storage.client_info = OAuthClientInformationFull(
        client_id=settings.mcp_oauth_client_id,
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="",
        client_name="ObjectOS",
    )
    provider = PersistentOAuthClientProvider(
        server_url=settings.mcp_endpoint,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        timeout=1800,
    )
    return provider, storage


@asynccontextmanager
async def altice_session(*, interactive: bool = False) -> AsyncIterator[ClientSession]:
    settings = get_settings()
    provider, storage = create_oauth_provider(interactive=interactive)
    headers = {
        "X-API-Key": settings.mcp_api_key,
        "X-Client-Type": settings.mcp_client_type,
        "Content-Type": "application/json",
    }
    if storage.tokens and (
        storage.oauth_metadata is None or storage.protected_resource_metadata is None
    ):
        await _restore_discovery(provider, storage)
    async with streamablehttp_client(
        settings.mcp_endpoint, headers=headers, timeout=5, auth=provider, terminate_on_close=False
    ) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _restore_discovery(
    provider: PersistentOAuthClientProvider, storage: JsonTokenStorage
) -> None:
    """Persist SDK discovery metadata so refresh uses the right issuer after restarts."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
        if storage.protected_resource_metadata is None:
            challenge_request = httpx.Request("POST", settings.mcp_endpoint)
            challenge = httpx.Response(401, request=challenge_request)
            request = await provider._discover_protected_resource(challenge)
            response = await client.get(request.url, headers=request.headers)
            await provider._handle_protected_resource_response(response)
        if storage.oauth_metadata is None:
            for url in provider._get_discovery_urls():
                response = await client.get(
                    url, headers={MCP_PROTOCOL_VERSION: LATEST_PROTOCOL_VERSION}
                )
                if response.status_code == 200:
                    try:
                        await provider._handle_oauth_metadata_response(response)
                    except Exception:
                        continue
                    break


async def login() -> None:
    settings = get_settings()
    server, _ = await _listener(settings.mcp_oauth_callback_url, settings.mcp_oauth_callback_port)
    server.close()
    await server.wait_closed()
    print(
        f"Callback OAuth disponível na porta {settings.mcp_oauth_callback_port}; a abrir o browser."
    )
    async with altice_session(interactive=True):
        pass
    path = settings.mcp_token_path
    if not path.is_file():
        raise RuntimeError("O servidor não iniciou OAuth; não foi criada uma sessão OAuth")
    os.chmod(path, 0o600)
    print("Autenticação MCP concluída. Tokens persistidos com permissões 600.")


def _schema_for_tool(tool: object) -> dict[str, object]:
    schema = getattr(tool, "inputSchema", {}) or {}
    return (
        schema.model_dump(mode="json", exclude_none=True)
        if hasattr(schema, "model_dump")
        else schema
    )


async def doctor() -> None:
    settings = get_settings()
    _, storage = create_oauth_provider()
    if storage.tokens is None:
        raise RuntimeError("Sem sessão OAuth persistida; execute make mcp-login primeiro")
    async with altice_session() as session:
        result = await session.list_tools()
    print("MCP operacional: initialize() e tools/list concluídos.")
    for tool in result.tools:
        print(
            json.dumps(
                {"name": tool.name, "inputSchema": _schema_for_tool(tool)}, ensure_ascii=False
            )
        )
    print(f"Sessão carregada de {settings.mcp_token_path}; permissões protegidas.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sessão MCP Altice do ObjectOS")
    parser.add_argument("command", choices=("login", "doctor"))
    command = parser.parse_args().command
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        asyncio.run(login() if command == "login" else doctor())
    except KeyboardInterrupt:
        print("Operação cancelada; autenticação não confirmada.")
        raise SystemExit(130) from None
    except OAuthCallbackError as exc:
        print(f"Autorização MCP recusada (OAuth error: {exc}).")
        raise SystemExit(1) from None
    except Exception as exc:
        nested = [exc]
        while nested:
            item = nested.pop()
            if isinstance(item, OAuthCallbackError):
                print(f"Autorização MCP recusada (OAuth error: {item}).")
                raise SystemExit(1) from None
            if isinstance(item, BaseExceptionGroup):
                nested.extend(item.exceptions)
        # OAuth/HTTP exceptions may embed URLs, headers or response bodies; expose only class.
        print(f"MCP {command} falhou ({type(exc).__name__}). Verifique configuração e rede.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
