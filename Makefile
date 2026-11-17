# Único ponto de entrada de comandos (local, agentes e CI usam os mesmos).
SHELL := bash
BACKEND  := app/backend
FRONTEND := app/frontend

.PHONY: dev down test lint contracts build android smoke check worktree mcp-login mcp-doctor mcp-up mcp-down

dev:  ## ambiente completo com hot reload (Docker)
	docker compose -f app/compose.yaml up --build

down:
	docker compose -f app/compose.yaml down

test:  ## pytest — fora de `check` durante a hackathon (sem testes nesta fase)
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
	@trap 'docker compose -f app/compose.yaml down -v >/dev/null 2>&1' EXIT; \
	export BACKEND_PORT=$${BACKEND_PORT:-18000} FRONTEND_PORT=$${FRONTEND_PORT:-15173}; \
	docker compose -f app/compose.yaml up --build -d --wait --wait-timeout 180 && \
	curl -fsS localhost:$$BACKEND_PORT/healthz | grep -q '"status":"ok"' && \
	curl -fsS localhost:$$FRONTEND_PORT/ | grep -q 'HomeMind Spaces' && \
	curl -fsS localhost:$$FRONTEND_PORT/healthz | grep -q '"status":"ok"' && echo "smoke OK"

check: lint build  ## tudo o que o CI exige (sem Docker, sem testes)
	docker compose -f app/compose.yaml config -q

mcp-login:  ## autenticação OAuth interativa Altice no host
	uv run --project $(BACKEND) --env-file app/.env python -m homemind.connectors.altice_auth login

mcp-doctor:  ## initialize e tools/list no MCP real Altice
	uv run --project $(BACKEND) --env-file app/.env python -m homemind.connectors.altice_auth doctor

mcp-up:  ## backend MCP isolado (porta 18080; sem frontend/volumes partilhados)
	docker compose -p homemind-altice -f app/compose.mcp.yaml up --build -d --wait

mcp-down:  ## parar apenas o projeto MCP isolado
	docker compose -p homemind-altice -f app/compose.mcp.yaml down

worktree:  ## make worktree b=feat/US-12-nome -> ../homemind-US-12-nome (a partir de origin/main)
	@test -n "$(b)" || { echo "uso: make worktree b=feat/US-xx-nome"; exit 1; }
	git fetch -q origin main
	git worktree add ../homemind-$(notdir $(b)) -b $(b) origin/main
