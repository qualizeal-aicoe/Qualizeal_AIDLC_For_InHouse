#!/usr/bin/env bash
# The knowledge service on this machine, without containers: for the agent's knowledge gold set in CI, and for a laptop.
#
#   bash scripts/knowledge.sh start    index the documents, serve them on 127.0.0.1:8765, wait until it answers
#   bash scripts/knowledge.sh stop
#
# It listens on 127.0.0.1 only, and trusts identity headers only from this machine (knowledge/arag.toml [identity]).
set -euo pipefail
cd "$(dirname "$0")/../knowledge"
port="${KNOWLEDGE_PORT:-8765}"
mkdir -p .arag
# Stops a process and everything it started (uv, npx, go run and dotnet run each start the real server as a child).
kill_tree() {
  local p="$1" c
  for c in $(pgrep -P "$p" 2>/dev/null); do kill_tree "$c"; done
  kill "$p" 2>/dev/null || true
}
case "${1:-}" in
  start)
    uv run -m arag ingest
    nohup uv run -m arag serve --host 127.0.0.1 --port "$port" > .arag/serve.log 2>&1 &
    echo $! > .arag/serve.pid
    for _ in $(seq 1 90); do
      if python3 -c "import sys, urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:$port/api/health', timeout=2)" 2>/dev/null; then
        echo "The knowledge service answers on 127.0.0.1:$port."
        exit 0
      fi
      sleep 1
    done
    echo "The knowledge service did not start:"
    tail -20 .arag/serve.log
    exit 1
    ;;
  stop)
    if [ -f .arag/serve.pid ]; then kill_tree "$(cat .arag/serve.pid)"; rm -f .arag/serve.pid; fi
    ;;
  *)
    echo "usage: bash scripts/knowledge.sh start|stop"
    exit 2
    ;;
esac
