# Backend e frontend

## Backend

`app/backend/src/homemind/`

| Pasta | Conteúdo |
|---|---|
| `core/` | configuração, SQLite (`db.py`), barramento (`events.py`), papéis (`access.py`), arranque |
| `contracts/` | modelos partilhados, eventos de domínio, fixtures da casa demo |
| `connectors/` | `fake_home`, `mcp_home`, `altice_auth`, `write_grant`, `mcp_verify` |
| `features/<nome>/` | `households`, `appliances`, `energy`, `billing`, `notifications`, `presence`, `safety`, `agent`, `automations`, `integration`, `auth`, `health`, `video`, `mcp` |
| `demo/` | base de demo determinística e contas do Authentik local |

Os routers são descobertos em `features/*/router.py`. Cada feature vive na sua pasta, com testes ao lado.

## Frontend

`app/frontend/src/`: `app`, `pages`, `components`, `hooks`, `services`, `types`. Os tipos da API são gerados por `make contracts`.

Páginas existentes: Início, Consumo, Aparelhos, Notificações, Orçamento, Contas e recibos, Regras da casa e Assistente. A página do assistente é um placeholder (<span class="estado estado--plan">PLANEADO</span>).

## Módulos de produto

| Módulo | Responsabilidade |
|---|---|
| `households` | Casas, quartos, moradores, permissões |
| `energy` | Dispositivos, leituras, degraus, assinaturas |
| `presence` | Câmara na porta, presença, estado da casa |
| `billing` | Atribuição, fatura, recibos, orçamentos, alertas |
| `notifications` | Centro de notificações, confirmações, preferências |
| `agent` | Assistente de IA, ações sugeridas |

*Fontes canónicas: `docs/architecture.md`, `app/backend/AGENTS.md`, `app/frontend/AGENTS.md`.*
