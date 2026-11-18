# Alternativas em Docker (nomes inalterados): stack completa, smoke, APK e demo web em contentores.
# O fluxo recomendado (Authentik em Docker; backend/frontend no anfitrião) está no Makefile.
.PHONY: dev auth smoke android demo-web-up demo-web-down demo-web-reset demo-web-clean

dev:  ## ambiente completo com hot reload (Docker)
	docker compose -f app/compose.yaml up --build

auth: auth-up  # nome antigo de auth-up

smoke:  ## sobe a stack, valida backend/frontend/proxy, desliga
	@trap 'docker compose -p homemind-smoke -f app/compose.yaml down -v >/dev/null 2>&1' EXIT; \
	export BACKEND_PORT=$${BACKEND_PORT:-18000} FRONTEND_PORT=$${FRONTEND_PORT:-15173} AUTHENTIK_PORT=$${AUTHENTIK_PORT:-19000}; \
	docker compose -p homemind-smoke -f app/compose.yaml up --build -d --wait --wait-timeout 180 && \
	curl -fsS localhost:$$BACKEND_PORT/healthz | grep -q '"status":"ok"' && \
	curl -fsS localhost:$$FRONTEND_PORT/ | grep -q 'Conta Certa' && \
	curl -fsS localhost:$$FRONTEND_PORT/healthz | grep -q '"status":"ok"' && echo "smoke OK"

android: contracts  ## APK debug -> app/frontend/android/app/build/outputs/apk/debug/ (requer JDK 21 + ANDROID_HOME)
	cd $(FRONTEND) && VITE_API_URL=$${VITE_API_URL:-http://localhost:8000} npm run build && npx cap sync android
	cd $(FRONTEND)/android && ./gradlew --no-daemon assembleDebug

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
