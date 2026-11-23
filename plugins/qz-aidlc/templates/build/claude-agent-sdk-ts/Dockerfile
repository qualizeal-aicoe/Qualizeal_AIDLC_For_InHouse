# syntax=docker/dockerfile:1
# Claude Agent SDK (TypeScript)
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    runs the gold set against the offline stub
#   docker run -p 8080:8080 -e AGENT_IDENTITY=oidc ... __SLUG__ npx tsx src/server.ts --host 0.0.0.0    serves it over HTTP
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM node:22-slim
# python3 runs the vendored QualiZeal kit (the gold-set runner); nothing else uses it.
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
ENV NODE_ENV=production AGENT_MODE=stub
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --include=dev
COPY . .
RUN chown -R node /app
USER node
# Healthy when the HTTP interface answers /health or, when the image runs its gold set instead, when the agent loads.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["npx", "tsx", "src/server.ts", "--health"]
CMD ["python3", ".claude/qz/scripts/qz.py", "eval", "run", "--label", "container"]
