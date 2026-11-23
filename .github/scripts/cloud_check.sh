#!/usr/bin/env bash
# One cloud's templates for every starter, with no cloud account and nothing applied, ever:
#   1. each starter scaffolded, and `qz cloud add` writing its cloud/<cloud>/ folder;
#   2. `qz cloud lint` on every one of those folders (no key's value anywhere; on Kubernetes, SIE locked down);
#   3. the policy scan (Checkov) over all of them: every finding is listed, then the step fails;
#   4. OpenTofu: init, validate, and the plan tests against mock providers, for every starter;
#   5. on Kubernetes, SIE put back to its defaults (telemetry on, no gateway token): the lint and the plan tests must fail;
#   6. the gateway's image built and started with no network, as the user it runs as: healthy, its key enforced, and the
#      starter's own model names served.
#   cloud_check.sh <azure|aws|gcp|kubernetes> <work dir>     (run from the Studio's checkout)
set -euo pipefail
cloud=$1
work=$2
studio=$(pwd)
QZ=(uv run -q --no-project --python ">=3.11,<3.14" --with "pyyaml==6.0.3" python -I -B -X utf8 "$studio/plugins/qz-aidlc/scripts/qz.py")
checkov_version=3.4.7
CHECKOV=(uvx -q --python 3.12 --from "checkov==$checkov_version" checkov)
stacks=(langgraph openai-agents-py claude-agent-sdk-py claude-agent-sdk-ts go-anthropic maf-dotnet strands-agentcore
        mcp-server-py agent-memory-py text-to-sql cli-harness-py vectorless-rag advanced-rag)
rm -rf "$work" && mkdir -p "$work/.plugins"
export TF_PLUGIN_CACHE_DIR="$work/.plugins" TF_IN_AUTOMATION=1 TF_INPUT=0 CHECKPOINT_DISABLE=1
failed=()
skip() { [[ " ${CLOUD_CHECK_SKIP:-} " == *" $1 "* ]]; }   # a local run without Docker or Checkov: CLOUD_CHECK_SKIP="checkov docker"

echo "== 1. every starter, with its $cloud folder"
for st in "${stacks[@]}"; do
  "${QZ[@]}" build new "$st" "$work/$st" --name "Order Support" --no-kit > /dev/null
  "${QZ[@]}" cloud add "$cloud" --project "$work/$st" > /dev/null
done
dirs=(); for st in "${stacks[@]}"; do dirs+=("$work/$st/cloud/$cloud"); done

echo "== 2. qz cloud lint"
for d in "${dirs[@]}"; do "${QZ[@]}" cloud lint "$d" > "$d.lint.txt" || { cat "$d.lint.txt"; failed+=("lint ${d#"$work"/}"); }; done

echo "== 3. the policy scan (Checkov $checkov_version)"
scan=(); for d in "${dirs[@]}"; do scan+=(-d "$d"); done
if skip checkov; then echo "(skipped)"; else
  "${CHECKOV[@]}" "${scan[@]}" --framework terraform dockerfile --compact --quiet --skip-download --output cli || failed+=("the policy scan")
fi

echo "== 4. OpenTofu: init, validate and the plan tests, for every starter"
tofu version | head -1
first=""
for st in "${stacks[@]}"; do
  d="$work/$st/cloud/$cloud"
  # The first init downloads and checks each provider; the rest take them from the cache under the same lock file.
  [ -n "$first" ] && cp "$first/.terraform.lock.hcl" "$d/"
  if (cd "$d" && tofu init -backend=false -no-color > "$d.init.log" 2>&1 && tofu validate -no-color > "$d.validate.log" 2>&1 \
        && tofu test -no-color > "$d.test.log" 2>&1); then
    echo "PASS $st: $(grep -o 'Success! [0-9]* passed, 0 failed' "$d.test.log")"
    [ -n "$first" ] || first="$d"
  else
    echo "::error::$cloud / $st: OpenTofu init, validate or the plan tests failed"
    for f in "$d.init.log" "$d.validate.log" "$d.test.log"; do [ -f "$f" ] && { echo "--- ${f##*/}"; tail -n 60 "$f"; }; done
    failed+=("tofu $st")
  fi
done

if [ "$cloud" = kubernetes ]; then
  echo "== 5. SIE put back to its defaults: the lint and the plan tests must both fail"
  base="$work/langgraph/cloud/kubernetes"
  for case in telemetry auth; do
    neg="$work/negative-$case"
    rm -rf "$neg" && cp -r "$base" "$neg"
    python3 -I - "$neg/sie-values.yaml" "$case" <<'EOF'
import sys
p, case = sys.argv[1], sys.argv[2]
t = open(p, encoding="utf-8").read()
old, new = {"telemetry": ("  enabled: false                 # the workers send no usage telemetry", "  enabled: true"),
            "auth": ("    mode: token ", "    mode: none  ")}[case]
assert t.count(old) == 1, old
open(p, "w", encoding="utf-8").write(t.replace(old, new))
EOF
    if "${QZ[@]}" cloud lint "$neg" > "$neg.lint.txt"; then echo "::error::the lint passed with SIE's $case at its default"; failed+=("negative lint $case"); fi
    if (cd "$neg" && tofu test -no-color > "$neg.test.log" 2>&1); then
      echo "::error::the plan tests passed with SIE's $case at its default"; failed+=("negative tofu $case")
    else
      echo "SIE $case at its default: lint and plan tests fail, as they must"
    fi
  done
fi

echo "== 6. the gateway's image"
if skip docker; then echo "(skipped)"; else
g="$work/langgraph/cloud/$cloud/gateway"
docker build -q -t qz-gateway:ci "$g" > /dev/null
user=$(docker inspect --format '{{.Config.User}}' qz-gateway:ci)
key="sk-gateway-ci-$(openssl rand -hex 12)"
envs=(-e "LITELLM_MASTER_KEY=$key" -e LANGFUSE_PUBLIC_KEY=pk-lf-ci -e LANGFUSE_SECRET_KEY=sk-lf-ci -e LANGFUSE_HOST=http://127.0.0.1:3000)
case "$cloud" in
  aws) envs+=(-e AWS_REGION=us-east-1) ;;
  azure) envs+=(-e AZURE_AI_API_BASE=https://ci.services.ai.azure.com/anthropic -e AZURE_OPENAI_V1_BASE=https://ci.services.ai.azure.com/openai/v1 -e AZURE_AI_API_KEY=ci) ;;
  gcp) envs+=(-e GOOGLE_CLOUD_PROJECT=ci-project -e VERTEX_LOCATION=global) ;;
  kubernetes) envs+=(-e ANTHROPIC_API_KEY=ci -e SIE_API_BASE=http://sie-cluster-gateway.sie.svc:8080/v1 -e SIE_AUTH_TOKEN=ci) ;;
esac
docker rm -f qz-gateway > /dev/null 2>&1 || true
docker run -d --name qz-gateway --network none --cap-drop ALL --security-opt no-new-privileges "${envs[@]}" qz-gateway:ci > /dev/null
up=no
for _ in $(seq 1 90); do
  [ "$(docker inspect --format '{{.State.Running}}' qz-gateway)" = true ] || break
  if docker exec qz-gateway python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=4)" 2> /dev/null; then up=yes; break; fi
  sleep 2
done
if [ "$up" != yes ]; then
  echo "::error::the gateway's image did not come up healthy"; docker logs --tail 80 qz-gateway || true; failed+=("gateway image")
else
  probe='
import json, sys, urllib.error, urllib.request
def get(path, key=None):
    req = urllib.request.Request("http://127.0.0.1:4000" + path, headers={"Authorization": "Bearer " + key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""
status, _ = get("/v1/models")
status_ok, body = get("/v1/models", sys.argv[1])
uid = next(line.split()[1] for line in open("/proc/1/status") if line.startswith("Uid:"))
print(json.dumps({"without_key": status, "with_key": status_ok, "uid": uid,
                  "models": sorted(m["id"] for m in json.loads(body)["data"]) if status_ok == 200 else []}))'
got=$(docker exec qz-gateway python3 -c "$probe" "$key")
echo "gateway: $got (image user: $user)"
python3 -I - "$got" "$user" <<'EOF' || failed+=("gateway image checks")
import json, sys
got, user = json.loads(sys.argv[1]), sys.argv[2]
want = ["agent-model", "agent-model-fallback", "agent-model-small"]
problems = []
if got["without_key"] not in (401, 403): problems.append(f"without the gateway key, /v1/models answered {got['without_key']}")
if got["with_key"] != 200: problems.append(f"with the gateway key, /v1/models answered {got['with_key']}")
if got["models"] != want: problems.append(f"the gateway serves {got['models']}, not the starter's names {want}")
if got["uid"] in ("0", "") or user in ("", "0", "root"): problems.append(f"the gateway runs as uid {got['uid']} (image user {user!r})")
for p in problems: print(f"::error::{p}")
sys.exit(1 if problems else 0)
EOF
fi
docker rm -f qz-gateway > /dev/null 2>&1 || true
fi

if [ ${#failed[@]} -gt 0 ]; then
  echo "::error::$cloud: ${#failed[@]} check(s) failed: ${failed[*]}"
  exit 1
fi
note=""; [ -z "${CLOUD_CHECK_SKIP:-}" ] || note=" (skipped in this run: $CLOUD_CHECK_SKIP)"
echo "$cloud: every starter linted, scanned, validated and planned; the gateway's image healthy as a non-root user. Nothing applied.$note"
