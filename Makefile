# Único ponto de entrada de comandos (local, agentes e CI usam os mesmos).
SHELL := bash
BACKEND  := app/backend
FRONTEND := app/frontend

.PHONY: demo-web-up demo-web-down demo-web-reset demo-web-clean demo-prepare demo-reset demo-replay demo-verify dev auth down test lint contracts build android smoke check worktree mcp-login mcp-doctor mcp-up mcp-down mcp-demo mcp-demo-reload mcp-demo-build mcp-demo-logs mcp-demo-check mcp-demo-down mcp-writes-on mcp-writes-off mcp-writes-status mcp-verify presence-wifi-scan

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
	curl -fsS localhost:$$FRONTEND_PORT/ | grep -q 'Conta Certa' && \
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

# GPU só se o Docker tiver o runtime nvidia; sem ele a demo arranca em CPU.
MCP_GPU := $(if $(shell docker info 2>/dev/null | grep -i 'runtimes:.*nvidia'),-f app/compose.gpu.yaml)
MCP_DEMO := -p homemind-mcpdemo -f app/compose.yaml -f app/compose.mcp-demo.yaml $(MCP_GPU)
mcp-demo:  ## demo completa com YOLO; reutiliza containers/imagens, não toca no Authentik se nada mudou
	@[ "$$(docker image inspect -f '{{index .Config.Labels "homemind.extras"}}' homemind-mcpdemo-backend 2>/dev/null)" = visao ] \
	  || { echo "a construir a imagem do backend com YOLO (só a 1.ª vez; pesado)…"; docker compose $(MCP_DEMO) build backend; }
	@[ -f app/backend/data/modelos/yolo11s.pt ] && [ -f app/backend/data/modelos/yolo11s-pose.pt ] \
	  || echo "AVISO: pesos YOLO em falta em app/backend/data/modelos (a demo arranca sem deteções; ver features/visao/README.md)"
	docker compose $(MCP_DEMO) up -d
	@app/infra/mcp-demo-check.sh heal
	docker compose $(MCP_DEMO) up -d --wait
	@app/infra/mcp-demo-check.sh

mcp-demo-reload:  ## restart rápido só de backend+frontend (Authentik/Postgres intactos)
	docker compose $(MCP_DEMO) restart backend frontend

mcp-demo-build:  ## rebuild só de backend+frontend e recria-os (Authentik/volumes intactos)
	docker compose $(MCP_DEMO) build backend frontend
	docker compose $(MCP_DEMO) up -d --no-deps --wait backend frontend

mcp-demo-logs:  ## logs de backend+frontend (Ctrl-C para sair)
	docker compose $(MCP_DEMO) logs -f --tail=100 backend frontend

mcp-demo-check:  ## diagnóstico: containers, rede/DNS, proxy, REST, WebSocket, modo MCP (só leitura)
	@app/infra/mcp-demo-check.sh

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

presence-wifi-scan:  ## varrimento Wi-Fi no anfitrião -> backend (PRESENCE_WIFI_MODE=ingest; ver docs/modules/presence.md)
	uv run --project $(BACKEND) --env-file app/.env python -m homemind.features.presence.hostscan

worktree:  ## make worktree b=feat/US-12-nome -> ../homemind-US-12-nome (a partir de origin/main)
	@test -n "$(b)" || { echo "uso: make worktree b=feat/US-xx-nome"; exit 1; }
	git fetch -q origin main
	git worktree add ../homemind-$(notdir $(b)) -b $(b) origin/main

# DEMO-01: apenas a DB app/.demo-data/ (com marcador de segurança).
# --offline: nenhuma tentativa de baixar dependências durante a apresentação.
demo-prepare:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli prepare

demo-reset:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli reset

demo-replay:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli replay

demo-verify:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli verify

# Demo web local: Authentik com 6 contas (ana, bruno, carla, diogo, senhorio, operador; palavra-passe
# demo-conta-certa) + backend/frontend sobre uma CÓPIA da base de demo com os `sub` verdadeiros.
# Projeto Compose próprio e portas próprias: não toca na stack de `make dev`.
DW_PORTS := BACKEND_PORT=$${BACKEND_PORT:-28000} FRONTEND_PORT=$${FRONTEND_PORT:-25173} AUTHENTIK_PORT=$${AUTHENTIK_PORT:-29000}
DW := docker compose -p homemind-demoweb -f app/compose.yaml -f app/compose.demo-web.yaml
DW_WEB := uv run --offline --project $(BACKEND) python -m homemind.demo.web
demo-web-up:  ## cria/atualiza tudo e arranca; idempotente. Abrir http://localhost:25173
	@export $(DW_PORTS); \
	$(DW) stop backend frontend >/dev/null 2>&1; \
	$(DW) up -d --wait authentik-server authentik-worker && \
	$(MAKE) --no-print-directory demo-prepare >/dev/null && \
	$(DW_WEB) users --compose "$(DW)" && \
	$(DW_WEB) prepare && \
	$(DW_WEB) link --authentik http://127.0.0.1:$$AUTHENTIK_PORT --web http://localhost:$$FRONTEND_PORT && \
	$(DW) up -d --build --wait backend frontend && \
	echo "demo web: http://localhost:$$FRONTEND_PORT  (ana|bruno|carla|diogo|senhorio|operador / demo-conta-certa)"

demo-web-down:  ## pára (mantém contas e dados)
	@export $(DW_PORTS); $(DW) down

demo-web-reset:  ## recria só a base (cópia nova da demo), mantém as contas
	@export $(DW_PORTS); $(DW) stop backend frontend; $(DW_WEB) clean && $(MAKE) --no-print-directory demo-web-up

demo-web-clean:  ## apaga tudo: containers, volumes (Authentik) e a cópia da base
	@export $(DW_PORTS); $(DW) down -v; $(DW_WEB) clean
