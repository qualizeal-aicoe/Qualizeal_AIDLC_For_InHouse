#!/usr/bin/env bash
# The model gateway end to end for one agent starter, with no model and no account: the project's gold set through the
# real LiteLLM proxy against two stand-in providers, the traces to a stand-in Langfuse endpoint; then the checks (keys,
# traces, no prompt text), a failed provider and a spent budget both moving calls to the fallback.
#   gateway_check.sh <project dir>        (run from the Studio's checkout; the project was made by `qz build new`)
set -euo pipefail
proj=$1
studio=$(pwd)
work="${RUNNER_TEMP:-/tmp}/gateway"
rm -rf "$work" && mkdir -p "$work"
QZ=(uv run -q --no-project --python ">=3.11,<3.14" --with "pyyaml==6.0.3" --with "opentelemetry-proto==1.45.2" python -I -X utf8 "$studio/plugins/qz-aidlc/scripts/qz.py")
LITELLM=(uvx --from "litellm[proxy,proxy-runtime]==1.110.0" litellm)   # proxy-runtime: the OpenTelemetry packages the Langfuse callback needs
KIT=(uv run -q --no-project --python ">=3.11,<3.14" python -I -X utf8 .claude/qz/scripts/qz.py)   # the project's own kit
"${LITELLM[@]}" --help > /dev/null    # installed once, before anything waits on it
provider_key="sk-provider-$(openssl rand -hex 16)"
gateway_key="sk-gateway-$(openssl rand -hex 16)"
lf_auth="pk-lf-ci:sk-lf-$(openssl rand -hex 8)"
python3 -c 'import json,sys; json.dump({"provider": sys.argv[1], "gateway": sys.argv[2], "langfuse": sys.argv[3].split(":")[1]}, open(sys.argv[4], "w"))' \
  "$provider_key" "$gateway_key" "$lf_auth" "$work/secrets.json"

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
wait_for() {   # url, what
  for _ in $(seq 1 90); do curl -fsS -o /dev/null "$1" 2>/dev/null && return 0; sleep 1; done
  echo "::error::$2 did not come up"; tail -40 "$work"/*.log || true; exit 1
}
gateway() {    # config file
  STANDIN_PROVIDER_KEY="$provider_key" LITELLM_MASTER_KEY="$gateway_key" LANGFUSE_PUBLIC_KEY="${lf_auth%%:*}" LITELLM_LOCAL_MODEL_COST_MAP=True \
    LANGFUSE_SECRET_KEY="${lf_auth#*:}" LANGFUSE_HOST="http://127.0.0.1:4318" \
    "${LITELLM[@]}" --config "$1" --port 4000 > "$work/litellm.log" 2>&1 &
  gw=$!; pids+=("$gw")
  wait_for "http://127.0.0.1:4000/health/liveliness" "the LiteLLM proxy"
}
ask() {        # model -> which stand-in answered (by the count of lines in each log)
  local before1 before2
  before1=$(wc -l < "$work/primary.jsonl" 2>/dev/null || echo 0); before2=$(wc -l < "$work/fallback.jsonl" 2>/dev/null || echo 0)
  curl -fsS http://127.0.0.1:4000/v1/chat/completions -H "Authorization: Bearer $gateway_key" -H "Content-Type: application/json" \
    -d "{\"model\": \"$1\", \"messages\": [{\"role\": \"user\", \"content\": \"Where is my order ORD-1001?\"}]}" > /dev/null
  [ "$(wc -l < "$work/fallback.jsonl" 2>/dev/null || echo 0)" -gt "$before2" ] && echo fallback && return
  [ "$(wc -l < "$work/primary.jsonl" 2>/dev/null || echo 0)" -gt "$before1" ] && echo primary && return
  echo none
}

"${QZ[@]}" gateway standin --port 4010 --name primary --log "$work/primary.jsonl" > "$work/primary.log" 2>&1 & p1=$!; pids+=("$p1")
"${QZ[@]}" gateway standin --port 4011 --name fallback --log "$work/fallback.jsonl" > "$work/fallback.log" 2>&1 & pids+=("$!")
"${QZ[@]}" gateway langfuse --port 4318 --out "$work/spans.jsonl" --auth "$lf_auth" > "$work/langfuse.log" 2>&1 & pids+=("$!")
wait_for "http://127.0.0.1:4010/health" "the primary stand-in"
wait_for "http://127.0.0.1:4011/health" "the fallback stand-in"

cd "$proj"
"${QZ[@]}" gateway config --src gateway/litellm.yaml --out "$work/litellm.ci.yaml"
gateway "$work/litellm.ci.yaml"

echo "== the gold set through the gateway"
unset ANTHROPIC_API_KEY OPENAI_API_KEY AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN || true
AGENT_GATEWAY_URL=http://127.0.0.1:4000 AGENT_GATEWAY_KEY="$gateway_key" \
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318/api/public/otel OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20$(printf '%s' "$lf_auth" | base64 -w0)" \
  "${KIT[@]}" eval run --config evals/eval.gateway.json --label gateway
sleep 8   # the exporters' last batches

echo "== keys, traces and prompt text"
"${QZ[@]}" gateway verify --standin-log "$work/primary.jsonl" --standin-log "$work/fallback.jsonl" --spans "$work/spans.jsonl" \
  --secrets "$work/secrets.json" --recordings evals/recordings-gateway --scan .agent/gateway-audit.jsonl

echo "== a provider that fails: the call goes to the fallback"
[ "$(ask agent-model)" = primary ] || { echo "::error::the main model did not answer first"; exit 1; }
kill "$p1"; sleep 1
[ "$(ask agent-model)" = fallback ] || { echo "::error::with the main provider down, the call did not go to the fallback"; exit 1; }
"${QZ[@]}" gateway standin --port 4010 --name primary --log "$work/primary.jsonl" > "$work/primary.log" 2>&1 & pids+=("$!")
wait_for "http://127.0.0.1:4010/health" "the primary stand-in, again"

echo "== a spent budget: the call goes to the fallback"
kill "$gw"; wait "$gw" 2>/dev/null || true; sleep 1
"${QZ[@]}" gateway config --src gateway/litellm.yaml --out "$work/litellm.budget.yaml" --tiny-budget
gateway "$work/litellm.budget.yaml"
first=$(ask agent-model); sleep 2; second=$(ask agent-model)
[ "$first" = primary ] && [ "$second" = fallback ] || { echo "::error::budget: first $first, then $second (wanted primary, then fallback)"; exit 1; }
echo "Gateway check: the gold set, the keys, the traces, a failed provider and a spent budget all passed"
