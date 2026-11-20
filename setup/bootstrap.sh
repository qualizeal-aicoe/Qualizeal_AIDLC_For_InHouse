#!/usr/bin/env sh
# QualiZeal AI-DLC Studio: get this macOS or Linux machine ready, then check it. Safe to run again; no sudo needed.
# From the cloned repository run:  sh setup/bootstrap.sh
set -u
REPO="${1:-qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse}"
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
PATH="$HOME/.local/bin:$PATH"; export PATH
step() { printf '\n== %s\n' "$1"; }

step "Git"
command -v git >/dev/null 2>&1 || { echo "Git is missing: install it (xcode-select --install on macOS), then run this again."; exit 1; }
git --version

step "Claude Code"
command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash
claude --version || { echo "Claude Code did not install; see https://code.claude.com/docs/en/setup"; exit 1; }

step "uv, which runs the Studio's Python"
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version || { echo "uv did not install; see https://docs.astral.sh/uv/"; exit 1; }
uv python find ">=3.11,<3.14" >/dev/null 2>&1 || uv python install 3.12

step "The Studio in Claude Code"
export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1
claude plugin marketplace add "$REPO" || echo "  (already added, or not readable yet: the check below says which)"
claude plugin install qz-aidlc@qualizeal
claude plugin install qz-console@qualizeal

step "The check"
uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "$root/plugins/qz-aidlc/scripts/qz.py" doctor --fix --json "$root/doctor-report.json" --repo "$REPO"
code=$?
echo
if [ "$code" -eq 0 ]; then echo "Ready. Restart Claude Code, then send doctor-report.json to the session lead."
else echo "Fix the FAIL lines above, then run sh setup/bootstrap.sh again."; fi
exit "$code"
