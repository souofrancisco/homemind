"""Validação de access tokens do Authentik (JWT RS256 via JWKS)."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from homemind.core.config import get_settings

bearer = HTTPBearer(auto_error=False)


class User(BaseModel):
    sub: str
    email: str | None = None
    email_verified: bool = False
    name: str | None = None
    username: str | None = None
    groups: list[str] = []


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    s = get_settings()
    url = s.oidc_jwks_url or s.oidc_issuer.rstrip("/") + "/jwks/"
    return jwt.PyJWKClient(url, cache_keys=True, timeout=5)


def validate_access_token(token: str) -> User:
    """Validação única para REST e WS (token recebido na primeira mensagem)."""
    unauthorized = HTTPException(401, "Não autenticado", headers={"WWW-Authenticate": "Bearer"})
    s = get_settings()
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=s.oidc_issuer,
            audience=s.oidc_client_id,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        raise unauthorized from None
    return User(
        sub=claims["sub"],
        email=claims.get("email"),
        email_verified=claims.get("email_verified") is True,
        name=claims.get("name"),
        username=claims.get("preferred_username"),
        groups=claims.get("groups", []),
    )


def current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if cred is None:
        raise HTTPException(401, "Não autenticado", headers={"WWW-Authenticate": "Bearer"})
    return validate_access_token(cred.credentials)


CurrentUser = Annotated[User, Depends(current_user)]
