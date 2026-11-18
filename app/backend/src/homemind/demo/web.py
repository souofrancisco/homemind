"""Demo web LOCAL: cópia da base de demo + contas Authentik reais (só desenvolvimento).

A base original (`.demo-data`, protegida pelo `demo-reset`) nunca é aberta para escrita aqui.
A cópia (`.demo-web`) leva o seu próprio marcador; só essa é criada, alterada ou apagada.
O `sub` de cada conta vem de um login OIDC verdadeiro (Authorization Code + PKCE contra o
Authentik local) e só é gravado por este comando local: o frontend e o backend não escolhem
identidades e a validação de tokens não muda.

    python -m homemind.demo.web users|prepare|link|clean
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import httpx

from homemind.contracts import fixtures as fx
from homemind.demo.cli import DEMO_ROOT, FILE_NAME, DemoStore

APP = Path(__file__).resolve().parents[4]
WEB_ROOT = APP / ".demo-web"
WEB_FILE = "conta-certa-web.sqlite3"
WEB_MARKER = "conta-certa-DEMO-WEB-v1"
PASSWORD = "demo-conta-certa"  # só Authentik local de desenvolvimento
ACCOUNTS = {  # username Authentik -> (nome visível, residente das fixtures)
    "ana": ("Ana", fx.ANA),
    "bruno": ("Bruno", fx.BRUNO),
    "carla": ("Carla", fx.CARLA),
    "diogo": ("Diogo", fx.DIOGO),
    "senhorio": ("Senhorio", fx.LANDLORD),
    "operador": ("Operador", fx.OPERATOR),
}


class WebDemoError(RuntimeError):
    pass


def web_path() -> Path:
    return WEB_ROOT / WEB_FILE


def _is_web_copy(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute("SELECT token FROM demo_web_marker WHERE id=1").fetchone() == (
            WEB_MARKER,
        )
    except sqlite3.Error:
        return False


def prepare() -> str:
    """Cria a cópia se faltar. Existente: só confirma o marcador (nunca sobrescreve)."""
    path = web_path()
    if path.exists():
        with closing(sqlite3.connect(path)) as conn:
            if not _is_web_copy(conn):
                raise WebDemoError(f"{path} existe mas não é uma cópia web marcada; recusado")
        return "existente"
    source = DEMO_ROOT / FILE_NAME
    if not source.exists():
        raise WebDemoError("base de demo em falta: correr `make demo-prepare`")
    DemoStore(DEMO_ROOT)._guard(existing=True)  # a original tem de estar íntegra e sem WAL
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(WEB_ROOT, 0o777)  # o utilizador `app` do contentor tem de criar WAL/SHM
    tmp = WEB_ROOT / f".new-{secrets.token_hex(4)}.sqlite3"
    try:
        with (
            closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(tmp)) as dst,
        ):
            src.backup(dst)  # leitura da original; nada é escrito nela
            dst.execute(
                "CREATE TABLE demo_web_marker (id INTEGER PRIMARY KEY, token TEXT NOT NULL)"
            )
            dst.execute("INSERT INTO demo_web_marker VALUES (1, ?)", (WEB_MARKER,))
            dst.commit()
        os.chmod(tmp, 0o666)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return "criada"


def link(username: str, sub: str) -> None:
    """Associa um `sub` verdadeiro ao residente da conta, só na cópia web."""
    if username not in ACCOUNTS:
        raise WebDemoError(f"conta desconhecida: {username}")
    if not sub or len(sub) > 256:
        raise WebDemoError("sub inválido")
    resident = ACCOUNTS[username][1]
    with closing(sqlite3.connect(web_path())) as conn:
        if not _is_web_copy(conn):
            raise WebDemoError("não é uma cópia web marcada")
        if conn.execute(
            "SELECT 1 FROM resident WHERE auth_subject = ? AND id != ?", (sub, str(resident))
        ).fetchone():
            raise WebDemoError("sub já associado a outro residente")
        cur = conn.execute(
            "UPDATE resident SET auth_subject = ? WHERE id = ?", (sub, str(resident))
        )
        if cur.rowcount != 1:
            raise WebDemoError("residente inexistente na cópia")
        conn.commit()


def clean() -> None:
    path = web_path()
    if path.exists():
        with closing(sqlite3.connect(path)) as conn:
            if not _is_web_copy(conn):
                raise WebDemoError("recusado: não é uma cópia web marcada")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


# --- Authentik local ----------------------------------------------------------------------


def ensure_users(compose: list[str]) -> None:
    code = "\n".join(
        [
            "from authentik.core.models import User",
            f"pw = {PASSWORD!r}",
            f"for username, name in {({u: n for u, (n, _) in ACCOUNTS.items()})!r}.items():",
            "    u, _ = User.objects.get_or_create(username=username, defaults={'name': name})",
            # Sem email: com email o Authentik oferece o desafio MFA por email no login.
            "    u.name = name; u.email = ''; u.is_active = True; u.set_password(pw); u.save()",
            "print('ok')",
        ]
    )
    out = subprocess.run(
        [*compose, "exec", "-T", "authentik-server", "ak", "shell", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    if "ok" not in out.stdout:
        raise WebDemoError(f"falha a criar contas Authentik: {out.stderr[-400:]}")


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        raise WebDemoError(f"resposta não-JSON ({r.status_code}) de {r.request.url.path}") from None


def oidc_sub(authentik: str, web_url: str, username: str) -> str:
    """Login OIDC completo (código + PKCE) com o fluxo real; devolve o `sub` do access token."""
    redirect = f"{web_url}/auth/callback"
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    params = {
        "client_id": "homemind",
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": "openid profile email",
        "state": secrets.token_urlsafe(8),
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
    }
    with httpx.Client(timeout=20, follow_redirects=False) as http:
        r = http.get(f"{authentik}/application/o/authorize/", params=params)
        location = r.headers.get("location", "")
        # Fluxo de login: slug vem no caminho `/if/flow/<slug>/`.
        slug = urlparse(location).path.strip("/").split("/")[-1]
        query = urlparse(location).query
        url = f"{authentik}/api/v3/flows/executor/{slug}/?query={quote(query)}"
        challenge_json = _json(http.get(url))
        for _ in range(8):
            component = challenge_json.get("component")
            if component == "xak-flow-redirect":
                target = challenge_json["to"]
                break
            if component == "ak-stage-identification":
                body = {"component": component, "uid_field": username}
            elif component == "ak-stage-password":
                body = {"component": component, "password": PASSWORD}
            else:
                raise WebDemoError(f"etapa de login inesperada: {component}")
            r = http.post(url, json=body)
            if r.status_code == 302:  # etapa aceite: o Authentik manda ler a seguinte no destino
                url = authentik + r.headers["location"]
                r = http.get(url)
                if r.status_code == 302:  # fluxo concluído: o executor volta a si para o redirect
                    url = authentik + r.headers["location"]
                    r = http.get(url)
            challenge_json = _json(r)
        else:
            raise WebDemoError("login não terminou")
        target = target if target.startswith("http") else f"{authentik}{target}"
        for _ in range(5):
            r = http.get(target)
            target = r.headers.get("location", "")
            if target.startswith(redirect):
                break
            if not target.startswith("http"):
                target = f"{authentik}{target}"
        code = parse_qs(urlparse(target).query).get("code", [""])[0]
        if not code:
            raise WebDemoError("sem código de autorização")
        token = http.post(
            f"{authentik}/application/o/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": "homemind",
                "code_verifier": verifier,
            },
        ).json()
    payload = token["access_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return claims["sub"]


def _retry(fn, seconds: float = 120.0):
    """O blueprint do Authentik pode demorar a aplicar-se depois de o servidor estar saudável."""
    end = time.monotonic() + seconds
    while True:
        try:
            return fn()
        except (WebDemoError, httpx.HTTPError, KeyError, IndexError):
            if time.monotonic() > end:
                raise
            time.sleep(3)


def main() -> None:
    p = argparse.ArgumentParser(description="Demo web local (Authentik + cópia da base de demo)")
    p.add_argument("action", choices=("users", "prepare", "link", "clean"))
    p.add_argument("--compose", help="comando docker compose (para `users`)")
    p.add_argument("--authentik", default="http://localhost:29000")
    p.add_argument("--web", default="http://localhost:25173")
    args = p.parse_args()
    try:
        if args.action == "users":
            ensure_users(args.compose.split())
        elif args.action == "prepare":
            print("cópia web:", prepare())
        elif args.action == "link":
            for username in ACCOUNTS:
                sub = _retry(lambda u=username: oidc_sub(args.authentik, args.web, u))
                link(username, sub)
                print(f"{username}: ligado")
        else:
            clean()
    except (WebDemoError, sqlite3.Error, httpx.HTTPError, KeyError) as exc:
        sys.exit(f"DEMO WEB RECUSADA: {exc}")


if __name__ == "__main__":
    main()
