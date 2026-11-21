#!/usr/bin/env sh
# QualiZeal AI-DLC Studio: get this macOS or Linux machine ready, then check it. Safe to run again; no sudo needed.
# From the cloned repository run:  sh setup/bootstrap.sh
# To check only, installing nothing:  sh setup/bootstrap.sh --check-only
set -u
REPO="qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse"
CHECK=0
for a in "$@"; do
  case "$a" in
    --check-only) CHECK=1 ;;
    -*) echo "Unknown option $a: use --check-only, or a repository as owner/name"; exit 2 ;;
    *) REPO="$a" ;;
  esac
done
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
PATH="$HOME/.local/bin:$PATH"; export PATH
step() { printf '\n== %s\n' "$1"; }

step "Git"
command -v git >/dev/null 2>&1 || { echo "Git is missing: install it (xcode-select --install on macOS), then run this again."; exit 1; }
git --version

step "Claude Code"
if ! command -v claude >/dev/null 2>&1; then
  if [ "$CHECK" -eq 1 ]; then echo "Claude Code is missing: curl -fsSL https://claude.ai/install.sh | bash"; exit 1; fi
  curl -fsSL https://claude.ai/install.sh | bash
fi
claude --version || { echo "Claude Code did not install; see https://code.claude.com/docs/en/setup"; exit 1; }

step "uv, which runs the Studio's Python"
if ! command -v uv >/dev/null 2>&1; then
  if [ "$CHECK" -eq 1 ]; then echo "uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version || { echo "uv did not install; see https://docs.astral.sh/uv/"; exit 1; }
if ! uv python find ">=3.11,<3.14" >/dev/null 2>&1; then
  if [ "$CHECK" -eq 1 ]; then echo "No Python 3.11 to 3.13 found: uv python install 3.12"; exit 1; fi
  echo "No Python 3.11 to 3.13 found; uv installs Python 3.12 for the Studio (about 30 MB) ..."
  uv python install 3.12
fi

if [ "$CHECK" -eq 0 ]; then
  step "The Studio in Claude Code"
  # Claude Code fetches the Studio with git; HTTPS avoids a hang on an old SSH key.
  export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1
  claude plugin marketplace add "$REPO" || echo "  (already added, or not readable yet: the check below says which)"
  claude plugin install qz-aidlc@qualizeal
  claude plugin install qz-console@qualizeal
fi

step "The check"
fix="--fix"
[ "$CHECK" -eq 1 ] && fix=""
# $fix is left unquoted on purpose: when it is empty it must disappear, not become an empty argument.
uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "$root/plugins/qz-aidlc/scripts/qz.py" doctor $fix --json "$root/doctor-report.json" --repo "$REPO"
code=$?
echo
if [ "$code" -eq 0 ]; then echo "Ready. Restart Claude Code, then send doctor-report.json to the session lead."
else echo "Fix the FAIL lines above, then run sh setup/bootstrap.sh again. Send doctor-report.json to the session lead if you are stuck."; fi
exit "$code"
