# syntax=docker/dockerfile:1
# Agent memory (Python)
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    runs the gold set against the offline extractor
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_SYNC=1 PYTHONUNBUFFERED=1 AGENT_MODE=stub \
    VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project      # dev tools too: the image runs its own gold set
COPY . .
RUN uv sync --locked                           # the project itself
# The gold set runs on the image's own environment, so nothing is synced, built or downloaded when it runs.
RUN python3 -c "import json,pathlib; p=pathlib.Path('evals/eval.json'); c=json.loads(p.read_text()); a=c['adapter']['command']; c['adapter']['command']=['python']+a[a.index('python')+1:] if a[:2]==['uv','run'] else a; p.write_text(json.dumps(c, indent=2))"
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
# The policy loads and the entry point imports: enough to say the image is sound.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["python", "-c", "import mem.core"]
# By default the image proves itself: its gold set against the offline stub. Live runs set AGENT_MODE=live.
CMD ["python", ".claude/qz/scripts/qz.py", "eval", "run", "--label", "container"]
