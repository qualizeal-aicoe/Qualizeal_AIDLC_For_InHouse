# syntax=docker/dockerfile:1
# AWS: Strands agent on Bedrock AgentCore, with Kiro steering and specs
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    runs the gold set against the offline stub
#   docker run -p 8080:8080 -e AGENT_IDENTITY=oidc ... __SLUG__ python3 -m agent.server --host 0.0.0.0    serves it over HTTP
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 AGENT_MODE=stub
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
# Healthy when the HTTP interface answers /health or, when the image runs its gold set instead, when the agent imports.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["python3", "-m", "agent.server", "--health"]
CMD ["python3", ".claude/qz/scripts/qz.py", "eval", "run", "--label", "container"]
