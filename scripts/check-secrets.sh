#!/usr/bin/env bash
# Falha se ficheiros versionados parecerem conter segredos ou BD/.env.
set -euo pipefail
cd "$(dirname "$0")/.."
bad=0
if git ls-files | grep -Eq '(^|/)\.env$|\.(db|sqlite3?|pem|key)$'; then
  echo "ficheiro sensível versionado:"; git ls-files | grep -E '(^|/)\.env$|\.(db|sqlite3?|pem|key)$'; bad=1
fi
if git grep -InE 'gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|(TOKEN|SECRET|PASSWORD|API_KEY)=[^[:space:]]+' \
  -- . ':!.env.example' ':!scripts/check-secrets.sh' ':!*package-lock.json' ':!src/backend/tests/*'; then
  bad=1
fi
[ "$bad" = 0 ] && echo "sem segredos detetados"
exit "$bad"
