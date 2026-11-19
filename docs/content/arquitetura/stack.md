# Stack tecnológico

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| Persistência | SQLite com migrações em `core/migrations/` |
| Eventos | Barramento em processo, persistido em SQLite (`core/events.py`) |
| Frontend | React 19, Vite, TypeScript, Mantine |
| Autenticação | Authentik (OIDC, PKCE), em Docker |
| Dispositivos | MCP Altice (Connected Home) ou `FakeHome` simulado |
| Contrato API | OpenAPI gerado pelo backend → tipos TypeScript (`make contracts`) |
| Ferramentas | `uv` (Python), npm (Node 22+), Docker Compose v2, `make` |

Os nomes `homemind` (pacote Python, cliente OIDC, projeto Compose) são herdados do projeto anterior e mantêm-se.

O código ObjectOS (motor de regras, gestos e páginas antigas) foi removido na BASE-04 (#74); o registo histórico está em `docs/architecture/migration.md`.

*Fonte canónica: `CLAUDE.md`, `docs/architecture.md`.*
