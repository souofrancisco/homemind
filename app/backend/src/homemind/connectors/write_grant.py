"""Autorização temporária de escritas físicas (sessão de demonstração).

O grant é um ficheiro 0600 no volume de dados, criado só por quem tem shell no host/container
(`make mcp-writes-on`). Não existe endpoint HTTP de ativação. O `McpHome` lê-o em cada escrita:
apagar o ficheiro (`off`) ou expirar recusa tudo de imediato. A whitelist de ferramentas e
capabilities é independente e continua sempre ativa.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROLES = ("lamp", "plug")


@dataclass(frozen=True)
class Grant:
    expires_at: datetime
    roles: frozenset[str]
    granted_by: str


def read_grant(path: Path, max_minutes: int, now: datetime | None = None) -> Grant | None:
    """Grant válido, ou None (ausente, expirado, corrompido ou com TTL acima do limite)."""
    now = now or datetime.now(UTC)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(raw["expires_at"])
        roles = frozenset(r for r in raw["roles"] if r in ROLES)
        if expires.tzinfo is None or expires <= now or not roles:
            return None
        if expires > now + timedelta(minutes=max_minutes):  # ficheiro adulterado/TTL excessivo
            return None
        return Grant(expires, roles, str(raw.get("granted_by", "?")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_grant(path: Path, minutes: int, roles: tuple[str, ...], max_minutes: int) -> Grant:
    if not 1 <= minutes <= max_minutes:
        raise ValueError(f"duração tem de estar entre 1 e {max_minutes} minutos")
    if not roles or any(r not in ROLES for r in roles):
        raise ValueError(f"dispositivos permitidos: {', '.join(ROLES)}")
    expires = datetime.now(UTC) + timedelta(minutes=minutes)
    who = getpass.getuser()
    payload = {"expires_at": expires.isoformat(), "roles": list(roles), "granted_by": who}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".grant-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:  # mkstemp já cria com 0600
        json.dump(payload, f)
    os.replace(tmp, path)
    return Grant(expires, frozenset(roles), who)


def main() -> None:
    from homemind.core.config import get_settings

    s = get_settings()
    parser = argparse.ArgumentParser(description="Sessão de escritas físicas da demo")
    parser.add_argument("action", choices=("on", "off", "status"))
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--roles", default=",".join(ROLES), help="lamp,plug")
    args = parser.parse_args()
    path = s.mcp_write_grant_path
    if args.action == "on":
        if not s.enable_physical_writes:
            print("AVISO: ENABLE_PHYSICAL_WRITES=false; o grant não surte efeito até ser true.")
        g = write_grant(
            path,
            args.minutes,
            tuple(r.strip() for r in args.roles.split(",")),
            s.mcp_write_max_minutes,
        )
        print(
            f"Escritas autorizadas ({', '.join(sorted(g.roles))}) até {g.expires_at:%H:%M:%S} UTC."
        )
    elif args.action == "off":
        path.unlink(missing_ok=True)
        print("Escritas revogadas.")
    else:
        g = read_grant(path, s.mcp_write_max_minutes)
        flag = "true" if s.enable_physical_writes else "false"
        if g is None:
            print(f"Escritas BLOQUEADAS (sem grant válido; ENABLE_PHYSICAL_WRITES={flag}).")
        else:
            print(
                f"Escritas autorizadas ({', '.join(sorted(g.roles))}) até "
                f"{g.expires_at:%H:%M:%S} UTC; ENABLE_PHYSICAL_WRITES={flag}."
            )


if __name__ == "__main__":
    main()
