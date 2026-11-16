# HomeMind Spaces

📄 **Fonte de verdade (Google Docs):** https://docs.google.com/document/d/1b9Lq2ZejWwpkt-by3U_Belzig1Or-jZxCQE2yLQSoyU/edit?tab=t.0
(editável por quem tem o link — nunca colocar segredos lá)

Hackathon Altice Labs · 16–20 nov 2026 · equipa de 5.

## O que é / que problema resolve
Camada de "inteligência de ocupação" para alojamento temporário: liga **estadia → permissões → preferências → plano contextual → ações verificadas** aos dispositivos Altice (via MCP). Na mudança de hóspede, o gestor repete tarefas manuais (acesso, preparação, revogação); o HomeMind transforma check-in/check-out em decisões auditáveis, protegendo a privacidade do hóspede. Não é gestor de reservas nem Home Assistant.

## Stack
FastAPI + Pydantic + SQLite (backend) · React + Vite + TypeScript + Mantine (frontend) · Capacitor (Android) · Authentik (OIDC + PKCE) · Ruff · Docker Compose · GitHub Actions. Monólito modular, sem Redis/filas/microserviços.

## Arrancar (Docker)
```bash
cp app/.env.example app/.env      # opcional; defaults = SIMULATION, escritas físicas OFF
make dev   # = docker compose up --build  (backend + frontend + Authentik)
```
Frontend http://localhost:5173 · API http://localhost:8000 (docs `/docs`, `/healthz`, `/api/me`) · Authentik http://localhost:9000.
Login de desenvolvimento: `akadmin` / `homemind-dev` (só dev; mudar com `AUTHENTIK_ADMIN_PASSWORD`). O provider OIDC (`homemind`, público, PKCE) é criado automaticamente por `app/infra/authentik/homemind.yaml`. Se mudares `AUTHENTIK_PORT`/`FRONTEND_PORT`, o issuer e os redirect URIs acompanham via compose.

## Android (APK debug)
Requer JDK 21 e Android SDK (`ANDROID_HOME`, plataforma 36).
```bash
make android    # -> app/frontend/android/app/build/outputs/apk/debug/app-debug.apk
adb reverse tcp:8000 tcp:8000 && adb reverse tcp:9000 tcp:9000   # dispositivo/emulador → serviços locais
adb install -r app/frontend/android/app/build/outputs/apk/debug/app-debug.apk
```
A app usa o mesmo frontend; o login abre o navegador do sistema e volta por deep link (`pt.homemind.app://auth/callback`). Para outros URLs: `VITE_API_URL=… VITE_OIDC_AUTHORITY=… make android` (o issuer tem de coincidir com `OIDC_ISSUER` do backend).

## Verificar (CI = make check; sem testes automatizados na hackathon)
```bash
make check   # ruff + eslint + contrato OpenAPI→TS + build frontend + compose config
make smoke   # opcional, local: sobe a stack Docker e valida (fora do CI)
```
Requer `uv`, Node 22, Docker, make. Também: `make dev`, `make down`, `make lint`, `make android`.

## Equipa
Pessoa 1 MCP & dispositivos · 2 Espaços/estadias/permissões · 3 Frontend base · 4 Planos/regras/turnover · 5 Hóspede & QA. Detalhe: separador 31 do Docs. Mapeamento pessoa→GitHub user: *por preencher* (ver [docs/parallel-work.md](docs/parallel-work.md)).

## User Stories
14 US (P0/P1) nos separadores 09–22 do Docs e como issues GitHub (label `P0`/`P1`). Não duplicadas aqui.

## Contribuir
Regras para agentes e humanos: [AGENTS.md](AGENTS.md); trabalho paralelo: [docs/parallel-work.md](docs/parallel-work.md).

## O que depende da Altice (MCP)
Endpoint, transporte, auth, catálogo de tools, e se contacto de porta/lâmpada são expostos para leitura/escrita: **desconhecido até 16/11**. Template em [docs/mcp-capabilities.md](docs/mcp-capabilities.md); perguntas em [docs/mentor-questions.md](docs/mentor-questions.md). Sem MCP, só SIMULATION (rotulado) — não prova integração.

## Estado
Preparação (15/11): apenas infraestrutura e documentação + `/healthz`. Funcionalidades de produto só a partir de 16/11, conforme regulamento.
