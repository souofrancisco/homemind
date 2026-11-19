# Desenvolvimento local

**Regra:** Authentik em Docker; backend e frontend **no anfitrião**, com reload. Docker completo (`make dev`) continua a existir como alternativa (§ Alternativas).

## Pré-requisitos

Docker (Compose v2), `make`, [`uv`](https://docs.astral.sh/uv/), Node 22+.

## Arranque

```bash
make setup      # uv sync + npm ci + app/.env a partir de app/.env.example (uma vez)
make auth-up    # Authentik em Docker (uma vez; fica a correr; ~1 min no 1.º arranque)
make backend    # terminal 1: uvicorn --reload
make frontend   # terminal 2: Vite com hot reload
```

| Serviço | URL (omissão) | Variável |
|---|---|---|
| Aplicação | <http://localhost:5173> | `FRONTEND_PORT` |
| API | <http://localhost:8000> (`/healthz`, `/docs`, `/openapi.json`) | `BACKEND_PORT` |
| Authentik | <http://localhost:9000> | `AUTHENTIK_PORT` |

Portas: variável de ambiente > `app/.env` > omissão. O Makefile exporta-as para o Compose, o backend (`OIDC_ISSUER`, `CORS_ORIGINS`) e o frontend (`VITE_OIDC_AUTHORITY`, proxy `/api`). Mudar uma porta = mudá-la em `app/.env` e correr outra vez `make auth-up` (o redirect do Authentik depende de `FRONTEND_PORT`).

O Authentik usa o projeto Compose `homemind-auth` (volume próprio, independente do de `make dev`). Parar e reiniciar backend/frontend é só `Ctrl+C` e repetir; sessões e dados mantêm-se.

## Demo verificável (SIMULADA)

```bash
make demo-up      # Authentik + 6 contas + base de demo + backend/frontend em segundo plano (~20 s)
make demo-reset   # base de demo nova; mantém Authentik e contas
make down         # pára tudo (sem apagar volumes)
```

Contas (só Authentik local): `ana`, `bruno`, `carla`, `diogo` (moradores), `senhorio`, `operador`; palavra-passe `demo-conta-certa`. Logs e pids dos processos em segundo plano: `app/.run/` (ignorado pelo Git). Para ver/depurar, usar `make backend DEMO=1` e `make frontend` em terminais próprios.

A base de demo é `app/.demo-web/` (cópia da original `app/.demo-data/`, que nunca é aberta para escrita). Percurso e evidência: [`evidence/demo-web-2026-11-18/`](evidence/demo-web-2026-11-18/README.md).

## `app/.env`

Nada é obrigatório: `app/.env.example` arranca em FakeHome (SIMULADO). Secções (todas comentadas no ficheiro): motor (`HOME_BACKEND`, `PROFILE`), vídeo/visão, MCP Altice (`MCP_*`, `ENABLE_PHYSICAL_WRITES`), presença, faturação (`BILLING_IGNORE_WH_MONTH`, PROPOSTA), portas, Authentik (`AUTHENTIK_*`, só dev), assistente (`AGENT_*`). Nunca commitar `app/.env` nem `app/.mcp-auth/`.

## Comandos

`make help` lista os principais (`setup auth-up backend frontend demo-up demo-reset down test lint build check worktree`); `make help-all` lista todos.

| Antes | Agora |
|---|---|
| `make dev` | continua (Docker completo, `app/infra/make/docker.mk`) |
| `make auth` | `make auth-up` (`auth` mantém-se como alias) |
| `make down` | também pára backend/frontend locais |
| `make demo-web-up/-down/-reset/-clean` | continuam (demo em Docker, porta 25173); preferir `demo-up` |
| `make demo-reset` (reset da base original `.demo-data`) | `make demo-reset` recria a **cópia web**; a original recria-se com `uv run --offline --project app/backend python -m homemind.demo.cli reset` |
| `make demo-prepare/replay/verify` | inalterados |
| `make mcp-*`, `presence-wifi-scan` | inalterados (`app/infra/make/mcp.mk`; escritas físicas continuam a exigir `ENABLE_PHYSICAL_WRITES=true` + grant temporário) |

## Testes

`make check` = `lint` + `test` + `build` + `docker compose config`. Só `pytest`: `make test`. Sem hardware, rede, LLM nem MCP real (ver [`development/testing.md`](development/testing.md)).

## Alternativas (Docker)

`make dev` (stack completa com hot reload dentro de contentores), `make smoke`, `make demo-web-up` (demo em contentores, :25173), `make mcp-demo` (visão + MCP real).

## Problemas conhecidos

- `password authentication failed for user "authentik"` num Authentik antigo: o volume do projeto `homemind` foi criado com outra `AUTHENTIK_DB_PASSWORD`. `make auth-up` usa o projeto `homemind-auth` (volume novo) e não é afetado; não apagar volumes antigos sem confirmar.
- Portas 5173/8000 ocupadas por `make dev`: `make down` ou definir outras portas em `app/.env`.
- Redirect OIDC inválido depois de mudar `FRONTEND_PORT`: repetir `make auth-up`.
- Playwright MCP sem Chrome (`/opt/google/chrome/chrome`): `npx playwright install chrome` ou usar o Chromium de `~/.cache/ms-playwright`.
