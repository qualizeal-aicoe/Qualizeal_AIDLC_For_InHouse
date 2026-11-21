# syntax=docker/dockerfile:1
# OpenAI Agents SDK (Python)
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    runs the gold set against the offline stub
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_SYNC=1 PYTHONUNBUFFERED=1 AGENT_MODE=stub
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project      # dev tools too: the image runs its own gold set
COPY . .
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
# The policy loads and the entry point imports: enough to say the image is sound.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["uv", "run", "python", "-c", "import agent.app"]
# By default the image proves itself: its gold set against the offline stub. Live runs set AGENT_MODE=live.
CMD ["python3", ".claude/qz/scripts/qz.py", "eval", "run", "--label", "container"]
