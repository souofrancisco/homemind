# Backend e frontend

## Backend

`app/backend/src/homemind/`

| Pasta | Conteúdo |
|---|---|
| `core/` | configuração, SQLite (`db.py`), barramento (`events.py`), papéis (`access.py`), arranque |
| `contracts/` | modelos partilhados, eventos de domínio, fixtures da casa demo |
| `connectors/` | `fake_home`, `fake_mcp`, `mcp_home`, `mcp_collector`, `mcp_energy`, `mcp_sensors`, `mcp_sensor_collector`, `altice`, `altice_auth`, `write_grant`, `write_policy`, `mcp_verify`, `runbook` |
| `features/<nome>/` | `households`, `appliances`, `energy`, `billing`, `notifications`, `presence`, `safety`, `agent`, `automations`, `integration`, `auth`, `health`, `video`, `visao`, `mcp`, `retention`, `demo_live` |
| `demo/` | base de demo determinística e contas do Authentik local |

Os routers são descobertos em `features/*/router.py`. Cada feature vive na sua pasta, com testes ao lado.

## Frontend

`app/frontend/src/`: `app`, `pages`, `components`, `hooks`, `services`, `types`. Os tipos da API são gerados por `make contracts`.

Navegação principal (`app/routes.tsx`, filtrada por papel; o servidor aplica sempre o RBAC): **Hoje**, **Contas**, **Casa**, **Assistente** (só inquilinos) e **Diagnóstico** (só operador). Páginas secundárias: Consumo, Aparelhos, Orçamento, Notificações, Regras da casa e Definições.

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
