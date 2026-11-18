# Interface principal. Fluxo recomendado: Authentik em Docker; backend e frontend no anfitrião (reload).
#   make setup && make auth-up      (uma vez)      make backend  |  make frontend      (dois terminais)
#   make demo-up                    (demo verificável, em segundo plano)  ·  make down
# Alternativas e comandos especializados (mesmos nomes de sempre): app/infra/make/*.mk · `make help-all`.
SHELL := bash
BACKEND  := app/backend
FRONTEND := app/frontend
RUN      := app/.run

# Precedência: variável de ambiente > app/.env > omissão.
envv = $(or $($(1)),$(shell sed -n 's/^$(1)=\([^ \#]*\).*/\1/p' app/.env 2>/dev/null | tail -1),$(2))
BACKEND_PORT   := $(call envv,BACKEND_PORT,8000)
FRONTEND_PORT  := $(call envv,FRONTEND_PORT,5173)
AUTHENTIK_PORT := $(call envv,AUTHENTIK_PORT,9000)
export BACKEND_PORT FRONTEND_PORT AUTHENTIK_PORT   # o Compose também os lê (portas e redirect do Authentik)

OIDC := http://localhost:$(AUTHENTIK_PORT)/application/o/homemind/
AUTH := docker compose -p homemind-auth -f app/compose.yaml
ENVFILE := $(if $(wildcard app/.env),--env-file ../.env)
# DEMO=1: backend sobre a CÓPIA da base de demo (app/.demo-web), SIMULADO (FakeHome).
DEMO_DB := $(abspath app/.demo-web/conta-certa-web.sqlite3)
DEMO_ENV := $(if $(DEMO),PROFILE=demo HOME_BACKEND=fake DB_PATH=$(DEMO_DB))
WEBDEMO := uv run --offline --project $(BACKEND) python -m homemind.demo.web

.PHONY: help help-all setup auth-up backend frontend demo-up demo-reset down test lint contracts build check worktree demo-prepare demo-replay demo-verify
.DEFAULT_GOAL := help

help:  ## esta lista
	@grep -hE '^[a-z-]+:.*## ' Makefile | sed 's/:.*## /\t/' | column -t -s $$'\t'

help-all:  ## todos os comandos, incluindo MCP e Docker (app/infra/make/*.mk)
	@grep -hE '^[a-z-]+:.*## ' Makefile app/infra/make/*.mk | sed 's/:.*## /\t/' | column -t -s $$'\t'

setup:  ## dependências (uv sync, npm ci) e app/.env a partir do exemplo
	@[ -f app/.env ] || cp app/.env.example app/.env
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm ci --no-audit --no-fund

auth-up:  ## Authentik em Docker (:9000; só login, não apaga volumes)
	$(AUTH) up -d --wait authentik-server authentik-worker

backend:  ## backend local com reload (:8000); DEMO=1 usa a base de demo
	cd $(BACKEND) && $(DEMO_ENV) OIDC_ISSUER=$(OIDC) CORS_ORIGINS=http://localhost:$(FRONTEND_PORT) \
	  uv run $(ENVFILE) uvicorn homemind.main:app --reload --host 127.0.0.1 --port $(BACKEND_PORT)

frontend:  ## frontend local com hot reload (:5173)
	cd $(FRONTEND) && API_PROXY_TARGET=http://127.0.0.1:$(BACKEND_PORT) VITE_OIDC_AUTHORITY=$(OIDC) \
	  npm run dev -- --port $(FRONTEND_PORT) --strictPort

LOCAL := app/infra/local.sh

demo-up:  ## demo verificável: Authentik + 6 contas + base de demo + backend/frontend locais
	$(MAKE) --no-print-directory auth-up demo-prepare
	@$(LOCAL) stop
	$(WEBDEMO) users --compose "$(AUTH)"
	$(WEBDEMO) prepare
	$(WEBDEMO) link --authentik http://127.0.0.1:$(AUTHENTIK_PORT) --web http://localhost:$(FRONTEND_PORT)
	@$(LOCAL) start backend backend DEMO=1
	@$(LOCAL) start frontend frontend DEMO=1
	@for i in $$(seq 1 60); do curl -fsS localhost:$(BACKEND_PORT)/healthz >/dev/null 2>&1 && curl -fsS localhost:$(FRONTEND_PORT)/healthz >/dev/null 2>&1 && break; sleep 1; done; \
	  curl -fsS localhost:$(FRONTEND_PORT)/healthz >/dev/null || { echo "falhou: ver $(RUN)/*.log"; exit 1; }
	@echo "demo: http://localhost:$(FRONTEND_PORT)  (ana|bruno|carla|diogo|senhorio|operador / demo-conta-certa; SIMULADO)"

demo-reset:  ## recria a base de demo (cópia nova); mantém o Authentik e as contas
	@$(LOCAL) stop
	$(WEBDEMO) clean
	$(MAKE) --no-print-directory demo-up

down:  ## pára backend/frontend locais e os containers (sem apagar volumes)
	@$(LOCAL) stop
	$(AUTH) down
	@docker compose -f app/compose.yaml down 2>/dev/null; true   # stack `make dev` (se existir)

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

check: lint test build  ## validações locais (não sobe containers)
	docker compose -f app/compose.yaml config -q

worktree:  ## make worktree b=feat/US-12-nome -> ../homemind-US-12-nome (a partir de origin/main)
	@test -n "$(b)" || { echo "uso: make worktree b=feat/US-xx-nome"; exit 1; }
	git fetch -q origin main
	git worktree add ../homemind-$(notdir $(b)) -b $(b) origin/main

# DEMO-01: dataset determinístico em app/.demo-data (marcador de segurança). --offline: sem rede em apresentação.
demo-prepare:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli prepare
demo-replay:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli replay
demo-verify:
	uv run --offline --project $(BACKEND) python -m homemind.demo.cli verify

include app/infra/make/docker.mk app/infra/make/mcp.mk
