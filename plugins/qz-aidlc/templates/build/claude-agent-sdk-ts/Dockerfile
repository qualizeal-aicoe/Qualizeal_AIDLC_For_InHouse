# syntax=docker/dockerfile:1
# Claude Agent SDK (TypeScript)
#   docker build -t __SLUG__ .
#   docker run --rm --network none __SLUG__    runs the gold set against the offline stub
# Images are named by release tag (semantic-release): a rollback is the previous tag. See docs/release.md.
FROM node:22-slim
# python3 runs the vendored QualiZeal kit (the gold-set runner); nothing else uses it.
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
ENV NODE_ENV=production AGENT_MODE=stub
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --include=dev
COPY . .
RUN chown -R node /app
USER node
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["npx", "tsx", "-e", "import('./src/policy.ts')"]
CMD ["python3", ".claude/qz/scripts/qz.py", "eval", "run", "--label", "container"]
