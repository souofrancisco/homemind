# Comandos Makefile

`make help` lista os principais; `make help-all` lista todos (inclui MCP e Docker, em `app/infra/make/*.mk`).

| Comando | O que faz |
|---|---|
| `make setup` | Dependências (`uv sync`, `npm ci`) e `app/.env` a partir do exemplo |
| `make auth-up` | Authentik em Docker (:9000; só login, não apaga volumes) |
| `make backend` | Backend local com reload (:8000); `DEMO=1` usa a base de demo |
| `make frontend` | Frontend local com hot reload (:5173) |
| `make demo-up` | Demo verificável: Authentik + 6 contas + base de demo + backend/frontend locais |
| `make demo-reset` | Recria a base de demo (cópia nova); mantém Authentik e contas |
| `make down` | Pára backend/frontend locais e os containers (sem apagar volumes) |
| `make test` | `pytest` (lógica pura com fakes; sem hardware nem rede) |
| `make lint` | `ruff` + `eslint` |
| `make contracts` | OpenAPI do FastAPI → tipos TypeScript (gerados, não versionados) |
| `make build` | Typecheck e build do frontend contra o contrato atual |
| `make check` | Validações locais: lint + `pytest` + contrato + build + `docker compose config` |
| `make worktree b=feat/<n>-<nome>` | Cria `../homemind-<n>-<nome>` a partir de `origin/main` |

Alternativas em Docker: `make dev`, `make smoke`, `make demo-web-up` (porta 25173). Os comandos `mcp-*` e `presence-wifi-scan` tocam em hardware real; as escritas físicas exigem `ENABLE_PHYSICAL_WRITES=true` e autorização temporária.

!!! note "Documentação"
    Os comandos desta documentação (`mkdocs`, `docker compose -f docs/compose.yml`) não estão no Makefile. Ver [Este website](website.md).

*Fonte canónica: `Makefile` e `docs/development.md`.*
