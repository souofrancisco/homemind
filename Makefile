# Único ponto de entrada de comandos (local, agentes e CI usam os mesmos).
SHELL := bash
BACKEND  := app/backend
FRONTEND := app/frontend

.PHONY: dev auth down test lint contracts build android smoke check worktree mcp-login mcp-doctor mcp-up mcp-down mcp-demo mcp-demo-down mcp-writes-on mcp-writes-off mcp-writes-status mcp-verify

dev:  ## ambiente completo com hot reload (Docker)
	docker compose -f app/compose.yaml up --build

auth:  ## só o Authentik (login), para correr backend e frontend no host (ex.: visão com YOLO)
	docker compose -f app/compose.yaml up -d --wait authentik-server authentik-worker

down:
	docker compose -f app/compose.yaml down

test:  ## pytest (lógica pura com fakes; sem hardware, rede nem NVIDIA)
	cd $(BACKEND) && uv run pytest -q

lint:  ## ruff + eslint
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .
	cd $(FRONTEND) && npm ci --no-audit --no-fund && npm run lint

contracts:  ## OpenAPI do FastAPI -> tipos TS (gerados, não versionados)
	mkdir -p $(FRONTEND)/src/shared/api
	cd $(BACKEND) && uv run python -m homemind.openapi > ../frontend/src/shared/api/openapi.json
	cd $(FRONTEND) && npm run gen:api

build: contracts  ## typecheck + build do frontend contra o contrato atual
	cd $(FRONTEND) && npm run build

android: contracts  ## APK debug -> app/frontend/android/app/build/outputs/apk/debug/ (requer JDK 21 + ANDROID_HOME)
	cd $(FRONTEND) && VITE_API_URL=$${VITE_API_URL:-http://localhost:8000} npm run build && npx cap sync android
	cd $(FRONTEND)/android && ./gradlew --no-daemon assembleDebug

smoke:  ## sobe a stack, valida backend/frontend/proxy, desliga
	@trap 'docker compose -p homemind-smoke -f app/compose.yaml down -v >/dev/null 2>&1' EXIT; \
	export BACKEND_PORT=$${BACKEND_PORT:-18000} FRONTEND_PORT=$${FRONTEND_PORT:-15173} AUTHENTIK_PORT=$${AUTHENTIK_PORT:-19000}; \
	docker compose -p homemind-smoke -f app/compose.yaml up --build -d --wait --wait-timeout 180 && \
	curl -fsS localhost:$$BACKEND_PORT/healthz | grep -q '"status":"ok"' && \
	curl -fsS localhost:$$FRONTEND_PORT/ | grep -q 'ObjectOS' && \
	curl -fsS localhost:$$FRONTEND_PORT/healthz | grep -q '"status":"ok"' && echo "smoke OK"

check: lint test build  ## tudo o que o CI exige (não sobe containers)
	docker compose -f app/compose.yaml config -q

mcp-login:  ## autenticação OAuth interativa Altice no host
	uv run --project $(BACKEND) --env-file app/.env python -m homemind.connectors.altice_auth login

mcp-doctor:  ## só leitura no MCP real: tools/list + estado e último contacto da lâmpada/tomada
	uv run --project $(BACKEND) --env-file app/.env python -m homemind.connectors.altice_auth doctor

mcp-up:  ## backend MCP isolado (porta 18080; sem frontend/volumes partilhados)
	docker compose -p homemind-altice -f app/compose.mcp.yaml up --build -d --wait

mcp-down:  ## parar apenas o projeto MCP isolado
	docker compose -p homemind-altice -f app/compose.mcp.yaml down

MCP_DEMO := -p homemind-mcpdemo -f app/compose.yaml -f app/compose.mcp-demo.yaml
mcp-demo:  ## demo completa: frontend + Authentik + backend com HOME_BACKEND=mcp (escritas bloqueadas)
	docker compose $(MCP_DEMO) up --build -d --wait

mcp-demo-down:
	docker compose $(MCP_DEMO) down

# Sessão de escritas físicas (ENABLE_PHYSICAL_WRITES=true no .env + grant temporário).
# stack=demo para a demo completa; omissão = backend MCP isolado. Ex.: make mcp-writes-on minutes=15
MCP_STACK = $(if $(filter demo,$(stack)),$(MCP_DEMO),-p homemind-altice -f app/compose.mcp.yaml)
mcp-writes-on:  ## autoriza escritas na lâmpada+tomada por N minutos (máx. MCP_WRITE_MAX_MINUTES)
	docker compose $(MCP_STACK) exec backend python -m homemind.connectors.write_grant on --minutes $(or $(minutes),15) $(if $(roles),--roles $(roles))

mcp-writes-off:  ## revoga imediatamente as escritas
	docker compose $(MCP_STACK) exec backend python -m homemind.connectors.write_grant off

mcp-writes-status:
	docker compose $(MCP_STACK) exec backend python -m homemind.connectors.write_grant status

mcp-verify:  ## verificação física controlada (what=lamp|plug), pede autorização explícita
	uv run --project $(BACKEND) --env-file app/.env python -m homemind.connectors.mcp_verify $(what)

worktree:  ## make worktree b=feat/US-12-nome -> ../homemind-US-12-nome (a partir de origin/main)
	@test -n "$(b)" || { echo "uso: make worktree b=feat/US-xx-nome"; exit 1; }
	git fetch -q origin main
	git worktree add ../homemind-$(notdir $(b)) -b $(b) origin/main
