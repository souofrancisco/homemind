# MCP Altice, hardware e visão: comandos especializados (nomes inalterados). Incluído pelo Makefile.
# Escritas físicas: ENABLE_PHYSICAL_WRITES=true + grant temporário (make mcp-writes-on). Não alterar esta lógica sem issue.
.PHONY: mcp-login mcp-doctor mcp-up mcp-down mcp-demo mcp-demo-reload mcp-demo-build mcp-demo-logs mcp-demo-check mcp-demo-down mcp-writes-on mcp-writes-off mcp-writes-status mcp-verify presence-wifi-scan

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
