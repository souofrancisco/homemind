#!/usr/bin/env bash
# Smoke test: sobe a stack, espera pelos serviços, valida respostas, desliga.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'docker compose down -v >/dev/null 2>&1' EXIT
export BACKEND_PORT=${BACKEND_PORT:-18000} FRONTEND_PORT=${FRONTEND_PORT:-15173}
docker compose up --build -d --wait --wait-timeout 180
curl -fsS http://localhost:$BACKEND_PORT/healthz | grep -q '"status":"ok"'
curl -fsS http://localhost:$FRONTEND_PORT/ | grep -q 'HomeMind Spaces'
curl -fsS http://localhost:$FRONTEND_PORT/healthz | grep -q '"status":"ok"' # via proxy do Vite
echo "smoke OK"
