# syntax=docker/dockerfile:1
# The model gateway for this cloud: LiteLLM with this folder's litellm.yaml baked in. Build it from this folder,
# name it by release tag like the agent's image, and push both to the client's registry:
#   docker build -t <registry>/<name>-gateway:<tag> .
# Pinned: change the version on purpose, after reading LiteLLM's release notes, and run the gateway check again.
# LiteLLM's own non-root build of that release: it runs as user 65534 with its home in /app.
FROM ghcr.io/berriai/litellm-non_root:1.110.0
COPY litellm.yaml /app/litellm.yaml
# Prices (for the budgets) come from the price list inside this pinned image, not one fetched from GitHub at each start:
# a list that changes on its own would change what a budget allows. A model the list lacks gets input_cost_per_token
# and output_cost_per_token in litellm.yaml.
ENV LITELLM_LOCAL_MODEL_COST_MAP=True
# Not root: the image's own user, stated here so the cloud templates and this file say the same thing.
USER 65534
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=4)"]
CMD ["--config", "/app/litellm.yaml", "--port", "4000"]
