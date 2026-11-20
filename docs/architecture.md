# Arquitetura (implementada)

Só o que existe na `main`. O que é proposta ou desenho detalhado está em [`architecture/`](architecture/overview.md) (marcado PLANEADO/IMPLEMENTADO) e nas issues.

## Visão

```text
FakeHome (SIMULADO) ou McpHome (MCP Altice) → energia: degraus, sessões, assinaturas
  → eventos de domínio persistentes (SQLite, `core/events.py`, idempotentes por id)
  → billing: atribuição (quarto / pergunta / igual) → notificação «De quem é esta conta?» → voto
  → fatura do senhorio → repartição quarto/comum/resíduo → recibos → orçamento 50/80/100 %
  → REST (`/api/*`, FastAPI) → app React por papel (morador · senhorio · operador)
```

Um processo FastAPI; routers descobertos em `features/*/router.py` (`core/features.py`); SQLite com migrações em `core/migrations/`; login por Authentik (OIDC, PKCE), `sub` → membership → papel (`core/access.py`).

## Onde está cada coisa

| Caminho | Conteúdo |
|---|---|
| `app/backend/src/homemind/core/` | config, SQLite (`db.py`), barramento (`events.py`), papéis (`access.py`), arranque |
| `…/contracts/` | modelos partilhados, eventos de domínio, `fixtures.py` (casa demo) |
| `…/connectors/` | `fake_home`, `fake_mcp`, `mcp_home`, `mcp_collector`, `mcp_energy`, `mcp_sensors`, `mcp_sensor_collector`, `altice`, `altice_auth`, `write_grant`, `write_policy`, `mcp_verify`, `runbook` |
| `…/features/<nome>/` | `households`, `appliances`, `energy`, `billing`, `notifications`, `presence`, `safety`, `agent`, `automations`, `integration`, `auth`, `health`, `video`, `visao`, `mcp`, `retention`, `demo_live` |
| `…/demo/` | `cli.py` (base de demo determinística), `web.py` (contas Authentik + cópia web) |
| `app/frontend/src/` | `app`, `assets`, `components`, `hooks`, `pages`, `services`; tipos da API gerados por `make contracts` em `shared/api/` (não versionados) |
| `app/infra/` | blueprint do Authentik, `local.sh`, alvos `make` auxiliares |

## Regras de arquitetura

- **Uma feature não importa outra**: comunica por `contracts/` e eventos. Recursos partilhados (SQLite, barramento) vivem em `core/` (P5).
- **Contratos** (`contracts/`, eventos, modelos da API, [`architecture/contracts.md`](architecture/contracts.md)) mudam juntos, com acordo da equipa.
- Permissões no servidor por papel, DTOs distintos; rota nova ⇒ teste papel × rota. O senhorio nunca recebe presença, horários nem aparelhos.
- Dinheiro em cêntimos, energia em Wh, ausência = `None`; proveniência `measured | estimated | inferred | simulated` em tudo o que é medido ou calculado.
- O SDK `mcp` só é importado em `connectors/`; o resto conhece o protocolo `Home`.
- Eventos imutáveis, consumidores idempotentes, sem imagens nem IDs externos no payload.

Detalhe do backend: [`app/backend/AGENTS.md`](../app/backend/AGENTS.md) · frontend: [`app/frontend/AGENTS.md`](../app/frontend/AGENTS.md) · migração do ObjectOS: [`architecture/migration.md`](architecture/migration.md).
