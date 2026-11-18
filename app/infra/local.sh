#!/usr/bin/env bash
# Processos locais em segundo plano (grupo próprio; pid e log em app/.run/).
#   local.sh start <nome> <make-alvo> [VAR=valor ...]   local.sh stop
set -u
RUN="$(cd "$(dirname "$0")/.." && pwd)/.run"
ROOT="$(dirname "$(dirname "$RUN")")"
mkdir -p "$RUN"

stop() {
  for pidfile in "$RUN"/*.pid; do
    [ -f "$pidfile" ] || continue
    kill -- "-$(cat "$pidfile")" 2>/dev/null
    rm -f "$pidfile"
  done
  return 0
}

case "${1:-}" in
  start)
    name=$2; shift 2
    cd "$ROOT" || exit 1
    setsid nohup make --no-print-directory "$@" >"$RUN/$name.log" 2>&1 </dev/null &
    echo $! >"$RUN/$name.pid"
    ;;
  stop) stop ;;
  *) echo "uso: local.sh start <nome> <alvo> [VAR=valor ...] | stop" >&2; exit 2 ;;
esac
