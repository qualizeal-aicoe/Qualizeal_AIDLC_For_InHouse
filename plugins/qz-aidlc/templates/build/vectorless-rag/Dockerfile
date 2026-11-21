# syntax=docker/dockerfile:1
# Vectorless RAG knowledge assistant (Python)
#   docker build -t __SLUG__ .
#   docker run --rm -p 127.0.0.1:8765:8765 __SLUG__    serves the chat page at http://127.0.0.1:8765
#   docker run --rm --network none __SLUG__ uv run -m vrag eval --gate    the gate, offline
#   A staged project builds this from stage 7, once every stage is in.
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_SYNC=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project      # dev tools too: the image runs its own gold set
COPY . .
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
# The index is built into the image: the documents it answers from are the ones it was built with.
RUN uv run -m vrag ingest
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)"]
# Listens on every interface inside the container; publish it to one host port (docker run -p 127.0.0.1:8765:8765).
CMD ["uv", "run", "-m", "vrag", "serve", "--host", "0.0.0.0", "--port", "8765"]
