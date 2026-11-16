#!/usr/bin/env bash
# Mesmos checks do CI, localmente.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd src/backend && ${PYTHON:-python} -m ruff check . && ${PYTHON:-python} -m pytest -q)
(cd src/frontend && npm ci && npm run lint && npm run build)
scripts/check-secrets.sh
docker compose config -q
