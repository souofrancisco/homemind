#!/usr/bin/env bash
# Diagnóstico da demo MCP (só leitura, sem escritas físicas). Uso: mcp-demo-check.sh [heal]
# heal: só repara (recria apenas o backend se estiver a correr sem rede) e sai.
set -u
P=(-p homemind-mcpdemo -f app/compose.yaml -f app/compose.mcp-demo.yaml)
FP=${FRONTEND_PORT:-5173}; BP=${BACKEND_PORT:-8000}
fail=0
ok()  { echo "OK    $*"; }
bad() { echo "FALHA $*"; fail=1; }
t()   { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
dc()  { docker compose "${P[@]}" "$@"; }

# Causa do 502: arranque com a porta já ocupada deixa o container sem endpoint de rede.
bid=$(dc ps -q backend 2>/dev/null)
if [ -n "$bid" ] && [ "$(docker inspect -f '{{len .NetworkSettings.Networks}}' "$bid")" = 0 ]; then
  bad "backend sem rede (porta $BP ocupada no arranque?)"
  if [ "${1:-}" = heal ]; then
    echo "      a recriar só o backend…"
    dc up -d --no-deps --force-recreate backend >/dev/null; exit $?
  fi
fi
[ "${1:-}" = heal ] && exit 0

for s in backend frontend authentik-server authentik-worker authentik-db; do
  id=$(dc ps -q "$s" 2>/dev/null)
  [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null)" = healthy ] \
    && ok "$s healthy" || bad "$s não está healthy"
done

t "DNS 'backend' dentro do frontend" dc exec -T frontend getent hosts backend
t "frontend -> http://backend:8000/healthz" dc exec -T frontend wget -qO- -T5 http://backend:8000/healthz
t "host :$BP/healthz (porta do backend publicada)" curl -fsS -m5 localhost:$BP/healthz
body=$(curl -fsS -m5 localhost:$FP/healthz 2>/dev/null)
echo "$body" | grep -q '"status":"ok"' && ok "proxy :$FP/healthz" || bad "proxy :$FP/healthz"
echo "$body" | grep -q '"backend":"mcp"' && ok "HOME_BACKEND=mcp" || bad "HOME_BACKEND não é mcp"
echo "$body" | grep -q '"physical_writes":false' && ok "escritas físicas desligadas" || bad "physical_writes não é false"
[ "$fail" = 0 ] && echo "demo OK" || echo "demo COM FALHAS"
exit $fail
