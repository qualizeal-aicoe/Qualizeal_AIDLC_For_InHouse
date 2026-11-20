#!/usr/bin/env sh
# QualiZeal AI-DLC Studio: add the marketplace and install both plugins in Claude Code (macOS, Linux, WSL).
# Safe to run again. The repository is private: sign in to GitHub on this machine first (GitHub CLI or Git Credential Manager).
set -e
REPO="${1:-qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse}"
if ! command -v claude >/dev/null 2>&1; then
  echo "Claude Code is not installed on this machine. Install it, then run this again."
  exit 1
fi
claude plugin marketplace add "$REPO" || echo "The marketplace is already added; continuing."
claude plugin install qz-aidlc@qualizeal
claude plugin install qz-console@qualizeal
echo "Installed. Open Claude Code in any folder and run /qz-aidlc:qz-setup to finish (plan, usage reading, projects folder)."
