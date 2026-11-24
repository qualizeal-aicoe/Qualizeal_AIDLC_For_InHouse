#!/usr/bin/env bash
# Deploy this commit's two images (the agent and the knowledge service) to one environment:
#
#   bash scripts/deploy.sh staging|production
#
# The pipeline calls it after every gate has passed: staging on its own, production only after a person approves.
# Until DEPLOY_COMMAND is set (a CI/CD variable, never a secret in this file) it says what it would do and deploys
# nothing, so the pipeline runs end to end with no cloud account. Set DEPLOY_COMMAND to what rolls an image tag out on
# your platform: the OpenTofu in cloud/ (`qz cloud add`), `kubectl set image`, `az containerapp update` and so on. It
# runs with ENVIRONMENT and TAG set.
set -euo pipefail
env="${1:?usage: bash scripts/deploy.sh staging|production}"
case "$env" in
  staging|production) ;;
  *) echo "unknown environment: $env"; exit 2 ;;
esac
tag="${DEPLOY_TAG:-${GITHUB_SHA:-${BUILD_SOURCEVERSION:-${CI_COMMIT_SHA:-local}}}}"
who="${DEPLOY_APPROVED_BY:-${GITHUB_ACTOR:-${BUILD_REQUESTEDFOR:-${GITLAB_USER_LOGIN:-}}}}"
if [ -z "${DEPLOY_COMMAND:-}" ]; then
  echo "No DEPLOY_COMMAND set: nothing deployed. It would roll agent:$tag and knowledge:$tag out to $env${who:+ (started by $who)}."
  exit 0
fi
echo "Deploying agent:$tag and knowledge:$tag to $env${who:+ (started by $who)}."
ENVIRONMENT="$env" TAG="$tag" bash -c "$DEPLOY_COMMAND"
