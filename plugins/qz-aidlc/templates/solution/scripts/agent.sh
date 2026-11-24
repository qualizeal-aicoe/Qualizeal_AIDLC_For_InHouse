#!/usr/bin/env bash
# The agent's HTTP interface on this machine, without containers: for the acceptance cases in CI, and for a laptop.
#
#   bash scripts/agent.sh start    serve on 127.0.0.1:8080 (stub model, demo identities, the knowledge service beside it)
#   bash scripts/agent.sh stop
#
# Demo identities are for a laptop and CI only: the agent refuses them when APP_ENV says production.
set -euo pipefail
cd "$(dirname "$0")/.."
port="${AGENT_PORT:-8080}"
mkdir -p .agent
# Stops a process and everything it started (uv, npx, go run and dotnet run each start the real server as a child).
kill_tree() {
  local p="$1" c
  for c in $(pgrep -P "$p" 2>/dev/null); do kill_tree "$c"; done
  kill "$p" 2>/dev/null || true
}
case "${1:-}" in
  start)
    rm -f .agent/acceptance.db
    AGENT_MODE="${AGENT_MODE:-stub}" AGENT_IDENTITY=demo KNOWLEDGE_URL="${KNOWLEDGE_URL:-http://127.0.0.1:8765}" \
      AGENT_STATE_DB=.agent/acceptance.db AGENT_AUDIT_LOG=.agent/acceptance-audit.jsonl \
      nohup __LOCAL_SERVE__ --host 127.0.0.1 --port "$port" > .agent/serve.log 2>&1 &
    echo $! > .agent/serve.pid
    for _ in $(seq 1 180); do
      if python3 -c "import urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:$port/health', timeout=2)" 2>/dev/null; then
        echo "The agent answers on 127.0.0.1:$port."
        exit 0
      fi
      sleep 1
    done
    echo "The agent did not start:"
    tail -30 .agent/serve.log
    exit 1
    ;;
  stop)
    if [ -f .agent/serve.pid ]; then kill_tree "$(cat .agent/serve.pid)"; rm -f .agent/serve.pid; fi
    ;;
  *)
    echo "usage: bash scripts/agent.sh start|stop"
    exit 2
    ;;
esac
