# HomeMind Spaces

📄 **Fonte de verdade (Google Docs):** https://docs.google.com/document/d/1b9Lq2ZejWwpkt-by3U_Belzig1Or-jZxCQE2yLQSoyU/edit?tab=t.0
(editável por quem tem o link — nunca colocar segredos lá)

Hackathon Altice Labs · 16–20 nov 2026 · equipa de 5.

## O que é / que problema resolve
Camada de "inteligência de ocupação" para alojamento temporário: liga **estadia → permissões → preferências → plano contextual → ações verificadas** aos dispositivos Altice (via MCP). Na mudança de hóspede, o gestor repete tarefas manuais (acesso, preparação, revogação); o HomeMind transforma check-in/check-out em decisões auditáveis, protegendo a privacidade do hóspede. Não é gestor de reservas nem Home Assistant.

## Stack
FastAPI + Pydantic + SQLite (backend) · React + Vite + TypeScript + Tailwind (frontend) · pytest + Ruff · Docker Compose · GitHub Actions. Monólito modular, sem Redis/filas/microserviços.

## Arrancar (Docker)
```bash
cp .env.example .env      # opcional; defaults = SIMULATION, escritas físicas OFF
docker compose up --build
```
Frontend http://localhost:5173 · API http://localhost:8000 · docs http://localhost:8000/docs · saúde http://localhost:8000/healthz. Dados SQLite persistem no volume `db`. Hot reload ativo (compose = ambiente de dev).

## Testes (iguais ao CI)
```bash
scripts/test.sh      # ruff + pytest + lint/build frontend + segredos + compose config
scripts/smoke.sh     # sobe a stack e valida backend/frontend
```
Sem Docker: `cd src/backend && pip install -e ".[dev]" && ruff check . && pytest` (Python 3.12) · `cd src/frontend && npm ci && npm run lint && npm run build`.

## Equipa
Pessoa 1 MCP & dispositivos · 2 Espaços/estadias/permissões · 3 Frontend base · 4 Planos/regras/turnover · 5 Hóspede & QA. Detalhe: separador 31 do Docs. Mapeamento pessoa→GitHub user: *por preencher* (ver [CONTRIBUTING](CONTRIBUTING.md)).

## User Stories
14 US (P0/P1) nos separadores 09–22 do Docs e como issues GitHub (label `P0`/`P1`). Não duplicadas aqui.

## Contribuir
Ver [CONTRIBUTING.md](CONTRIBUTING.md) e [AGENTS.md](AGENTS.md).

## O que depende da Altice (MCP)
Endpoint, transporte, auth, catálogo de tools, e se contacto de porta/lâmpada são expostos para leitura/escrita: **desconhecido até 16/11**. Template em [docs/mcp-capabilities.md](docs/mcp-capabilities.md); perguntas em [docs/mentor-questions.md](docs/mentor-questions.md). Sem MCP, só SIMULATION (rotulado) — não prova integração.

## Estado
Preparação (15/11): apenas infraestrutura e documentação + `/healthz`. Funcionalidades de produto só a partir de 16/11, conforme regulamento.
