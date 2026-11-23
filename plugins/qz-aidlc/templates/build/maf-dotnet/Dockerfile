# syntax=docker/dockerfile:1
# Microsoft Agent Framework (.NET)
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    answers one question offline; `--target gold` runs the gold set
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY . .
RUN dotnet test tests/Agent.Tests -c Release && dotnet publish src/Agent -c Release -o /out

# The gold set runs here, in its own stage, against the published build: `docker build --target gold .` fails
# when a case fails. The cases run the same Agent.dll the final image ships, from inside the project (out/).
FROM mcr.microsoft.com/dotnet/runtime:10.0 AS gold
# python3 runs the gold-set runner. apt reads only Ubuntu's main component, with no prompts, retries and a 30-second
# timeout; UBUNTU_MIRROR, when set, replaces the public mirror (a company's own, or GitHub's on its runners).
ARG UBUNTU_MIRROR=""
ARG DEBIAN_FRONTEND=noninteractive
RUN set -e; f=/etc/apt/sources.list.d/ubuntu.sources; . /etc/os-release; \
    if [ -n "$UBUNTU_MIRROR" ]; then \
      printf 'Types: deb\nURIs: %s\nSuites: %s %s-updates\nComponents: main\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' \
        "$UBUNTU_MIRROR" "$VERSION_CODENAME" "$VERSION_CODENAME" > "$f"; \
    elif [ -f "$f" ]; then sed -i 's/^Components: .*/Components: main/' "$f"; fi; \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::Languages=none update; \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends python3; \
    rm -rf /var/lib/apt/lists/*
ENV AGENT_MODE=stub
WORKDIR /src
COPY . .
COPY --from=build /out ./out
RUN python3 -c "import json,pathlib; p=pathlib.Path('evals/eval.json'); c=json.loads(p.read_text()); c['adapter']['command']=['dotnet','out/Agent.dll','--eval']; p.write_text(json.dumps(c, indent=2))" \
    && python3 .claude/qz/scripts/qz.py eval run --label container

FROM mcr.microsoft.com/dotnet/runtime:10.0
WORKDIR /app
COPY --from=build /out .
ENV AGENT_MODE=stub
USER $APP_UID
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["dotnet", "Agent.dll", "Where is my order ORD-1001?"]
ENTRYPOINT ["dotnet", "Agent.dll"]
CMD ["Where is my order ORD-1001?"]
