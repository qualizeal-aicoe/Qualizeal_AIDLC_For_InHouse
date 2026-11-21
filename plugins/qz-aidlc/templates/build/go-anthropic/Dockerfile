# syntax=docker/dockerfile:1
# Go agent on the Anthropic API
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    answers one question offline; `--target gold` runs the gold set
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go vet ./... && go test ./... && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/agent ./cmd/agent \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/evaladapter ./cmd/evaladapter

# The gold set runs here, in its own stage: `docker build --target gold .` fails when a case fails.
FROM python:3.12-slim AS gold
ENV AGENT_MODE=stub
WORKDIR /app
COPY . .
COPY --from=build /out/evaladapter /usr/local/bin/evaladapter
RUN python3 -c "import json,pathlib; p=pathlib.Path('evals/eval.json'); c=json.loads(p.read_text()); c['adapter']['command']=['evaladapter']; p.write_text(json.dumps(c))" \
    && python3 .claude/qz/scripts/qz.py eval run --label container

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/agent /agent
ENV AGENT_MODE=stub
USER nonroot
# distroless has no shell: the health check is the binary answering offline.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["/agent", "Where is my order ORD-1001?"]
ENTRYPOINT ["/agent"]
CMD ["Where is my order ORD-1001?"]
