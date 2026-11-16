# AGENTS.md — HomeMind Spaces
Aplica-se a Claude Code, Codex e outros agentes. Regras específicas: `backend/AGENTS.md`, `frontend/AGENTS.md`.

## Produto
Estadia → permissões → preferências → plano → ação verificada, sobre dispositivos Altice (MCP). Hackathon 16–20/11/2026. Fonte de verdade: https://docs.google.com/document/d/1b9Lq2ZejWwpkt-by3U_Belzig1Or-jZxCQE2yLQSoyU/edit?tab=t.0
**Ler a US relevante no Docs (separadores 09–22) e 23–30 antes de implementar.** Não copiar o Docs para o repo; contratos detalhados vivem no código (`app/backend/src/homemind/contracts/`) e em `docs/`.

## Stack e comandos
Python 3.12 (uv) · FastAPI · Pydantic · SQLite · pytest · Ruff | React · Vite · TS · Tailwind | Docker Compose.
- `make dev` · `make down` · `make test` · `make lint` · `make contracts` · `make smoke` · `make check` (= CI, sem Docker). Só `make`; não chamar ferramentas à mão.
- Correr `make check` antes de dar a tarefa por feita; não declarar "feito" sem o correr.

## Estrutura (feature-first)
- `app/backend/src/homemind/features/<feature>/` = `router.py` (expõe `router`), `schemas.py`, serviços, `tests/`. Routers descobertos automaticamente (`core/features.py`): ordem alfabética, rota duplicada falha o arranque.
- `core/` (config, descoberta) e `contracts/` (entidades partilhadas) são partilhados e pequenos; `connectors/` = gateway de dispositivos.
- `app/frontend/src/{app,features/<feature>,shared}`: componentes, hooks e `api.ts` da feature ficam na feature. Tipos da API vêm do OpenAPI do backend (`make contracts` → `shared/api/schema.d.ts`, gerado, não versionado).
- `docs/` · `shared/fixtures/`. Módulos: spaces, stays, permissions, devices, plans, turnover, events (P1: maintenance, ai).

## Adicionar uma feature
1. `make worktree b=feat/US-xx-nome`. 2. Criar `features/<nome>/{__init__.py,router.py,schemas.py,tests/}` (backend) e `features/<nome>/` (frontend). 3. Sem editar `main.py`/`App` para registar. 4. Rotas novas = tipos TS via `make contracts`. 5. `make check`.
Uma feature só importa outras via o seu serviço/schemas públicos, nunca internals. Ficheiros partilhados (ver `.github/CODEOWNERS`): só com razão no PR.

## Convenções
snake_case (Python), camelCase/PascalCase (TS). Ruff limpo. Datas UTC ISO-8601. Erros: 401 sem sessão, 403 sem autorização na estadia, 400 entrada inválida.

## Git
Uma tarefa = uma feature = um branch + um worktree (`make worktree`). Branch `feat/US-xx-nome`, `fix/…`, `chore/…`; PR pequeno e título `US-xx: …`, a partir de `main` atualizada, squash merge, sem push direto/force-push. Não alterar `.github/`, `Makefile`, lockfiles ou `core/` sem necessidade da tarefa. Contratos partilhados só mudam com acordo. Nunca commitar `.env`, SQLite, tokens, logs privados.

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
