# Configuração local

## Pré-requisitos

Docker (Compose v2), `make`, [`uv`](https://docs.astral.sh/uv/) e Node 22+.

## Arranque com reload

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

Portas: variável de ambiente > `app/.env` > omissão. Mudar uma porta = mudá-la em `app/.env` e correr outra vez `make auth-up` (o redirect do Authentik depende de `FRONTEND_PORT`).

## Demonstração verificável (SIMULADA)

```bash
make demo-up      # Authentik + 6 contas + base de demo + backend/frontend em segundo plano (~20 s)
make demo-reset   # base de demo nova; mantém Authentik e contas
make down         # pára tudo (sem apagar volumes)
```

Contas de demonstração (só no Authentik local): `ana`, `bruno`, `carla`, `diogo` (moradores), `senhorio` e `operador`. A palavra-passe está no `README.md` do repositório; é só de demonstração e não serve em mais lado nenhum.

## `app/.env`

Nada é obrigatório: `app/.env.example` arranca em FakeHome (SIMULADO). Secções: motor (`HOME_BACKEND`, `PROFILE`), vídeo, MCP Altice (`MCP_*`, `ENABLE_PHYSICAL_WRITES`), presença, faturação, portas, Authentik e assistente.

!!! danger "Segredos"
    `app/.env` e `app/.mcp-auth/` ficam fora do Git. Nunca os commitar, nem colar o seu conteúdo em issues, logs ou documentação.

## Problemas conhecidos

- Portas 5173/8000 ocupadas por `make dev`: `make down` ou definir outras portas em `app/.env`.
- Redirect OIDC inválido depois de mudar `FRONTEND_PORT`: repetir `make auth-up`.
- `password authentication failed for user "authentik"` num Authentik antigo: `make auth-up` usa o projeto `homemind-auth` (volume novo) e não é afetado.

*Fonte canónica: `docs/development.md`.*
