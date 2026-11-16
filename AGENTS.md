# AGENTS.md — HomeMind Spaces
Aplica-se a Claude Code, Codex e outros agentes. Regras específicas: `backend/AGENTS.md`, `frontend/AGENTS.md`.

## Produto
Estadia → permissões → preferências → plano → ação verificada, sobre dispositivos Altice (MCP). Hackathon 16–20/11/2026. Fonte de verdade: https://docs.google.com/document/d/1b9Lq2ZejWwpkt-by3U_Belzig1Or-jZxCQE2yLQSoyU/edit?tab=t.0
**Ler a US relevante no Docs (separadores 09–22) e 23–30 antes de implementar.** Não copiar o Docs para o repo; contratos detalhados vivem no código (`backend/app/contracts/`) e em `docs/`.

## Stack e comandos
Python 3.12 · FastAPI · Pydantic · SQLite · pytest · Ruff | React · Vite · TS · Tailwind | Docker Compose.
- `docker compose up --build` · `scripts/test.sh` · `scripts/smoke.sh` · `scripts/check-secrets.sh`
- Executar testes após **cada** alteração; não declarar "feito" sem os correr.

## Estrutura
`backend/app/{contracts,core,features,connectors}` · `frontend/src/{app,pages,components,features,api}` · `shared/fixtures` · `docs/`.
Módulos: spaces, stays, permissions, devices, plans, turnover, events (P1: maintenance, ai).

## Convenções
snake_case (Python), camelCase/PascalCase (TS). Ruff limpo. Datas UTC ISO-8601. Erros: 401 sem sessão, 403 sem autorização na estadia, 400 entrada inválida.

## Git
Branch `feat/US-xx` ou `chore/…`, PR pequeno para `main`, sem push direto, sem force-push. Contratos partilhados só mudam com acordo. Nunca commitar `.env`, SQLite, tokens, logs privados.

## Prioridades
P0 primeiro (MCP real → check-in/portal → privacidade/check-out → plano → turnover READY). P1 (US-09/10/14) só após G4. Nunca atrasar P0 por extras.

## Contratos a preservar
Space, User, Stay, StayPreference, StayAccess, DeviceBinding, DeviceState, Plan/PlanStep, HomeEvent (OPERATIONAL/PRIVATE), Turnover/Task. Estados: Stay PLANNED→ACTIVE→CLOSED; DeviceState AVAILABLE/STALE/UNAVAILABLE; ActionResult VERIFIED/FAILED/UNVERIFIED/UNSUPPORTED; Mode REAL/SIMULATION.

## REAL vs SIMULATION
Providers separados (`connectors/`), BD separada por modo. Nunca mostrar dados simulados como REAL. Só o conector Altice importa o SDK MCP. Só o ActionExecutor, após aprovação, pede escrita ao gateway.

## Segurança e privacidade
Autorização no backend em cada pedido. `ENABLE_PHYSICAL_WRITES=false` por defeito. Sem segredos no código/CI/Docs. Logs sanitizados. Gestor não vê eventos PRIVATE. Sem vigilância de hóspedes.

## Proibido
Inventar tools/schemas/capacidades MCP (nunca inferir do PDF do kit); hardcode de nomes de tools; retry automático de escritas; marcar VERIFIED sem releitura.

## Relatório de implementação (conciso)
Feito · Ficheiros · Testes executados (comando + resultado) · Por validar/bloqueado.
