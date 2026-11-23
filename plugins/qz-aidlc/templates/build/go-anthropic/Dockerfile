# syntax=docker/dockerfile:1
# Go agent on the Anthropic API
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    answers one question offline; `--target gold` runs the gold set
#   docker run -p 8080:8080 -v agent-state:/data -e AGENT_IDENTITY=oidc ... __SLUG__ /server --host 0.0.0.0    serves it over HTTP
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go vet ./... && go test ./... \
    && for c in agent server runs; do CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/$c ./cmd/$c || exit 1; done \
    && mkdir -p /out/data

# The gold set runs here, in its own stage, through the project's own adapter (go run ./evals/adapter):
# `docker build --target gold .` fails when a case fails. python3 runs the vendored QualiZeal kit.
FROM build AS gold
ARG DEBIAN_FRONTEND=noninteractive
RUN command -v python3 >/dev/null || (apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*)
ENV AGENT_MODE=stub
RUN python3 .claude/qz/scripts/qz.py eval run --label container

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/agent /out/server /out/runs /
# Runs that wait for a person, and the changes made, live in the state database: mount a volume on /data to keep them
# across containers (several instances share Postgres instead; see internal/agent/durable.go).
COPY --from=build --chown=65532:65532 /out/data /data
# Audit lines go to standard error, for the platform's log shipping.
ENV AGENT_MODE=stub AGENT_AUDIT_LOG=- AGENT_STATE_DB=/data/state.db
USER nonroot
# distroless has no shell: the health check is the server binary. Healthy when the HTTP interface answers /health or,
# when the image answers one question instead, when the state database opens.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["/server", "--health"]
CMD ["/agent", "Where is my order ORD-1001?"]
