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
RUN go vet ./... && go test ./... && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/agent ./cmd/agent

# The gold set runs here, in its own stage, through the project's own adapter (go run ./cmd/evaladapter):
# `docker build --target gold .` fails when a case fails. python3 runs the vendored QualiZeal kit.
FROM build AS gold
ARG DEBIAN_FRONTEND=noninteractive
RUN command -v python3 >/dev/null || (apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*)
ENV AGENT_MODE=stub
RUN python3 .claude/qz/scripts/qz.py eval run --label container

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/agent /agent
# Audit lines go to standard error, for the platform's log shipping (the image has no writable working folder).
ENV AGENT_MODE=stub AGENT_AUDIT_LOG=-
USER nonroot
# distroless has no shell: the health check is the binary answering offline.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["/agent", "Where is my order ORD-1001?"]
ENTRYPOINT ["/agent"]
CMD ["Where is my order ORD-1001?"]
