# __NAME__ on Google Cloud

`qz cloud add gcp` wrote this folder for __NAME__ (__STACK__): __SHAPE__. It is OpenTofu, which Terraform also reads.
Nobody has applied it. The Studio's CI validates these files, plans them with the Google provider mocked and scans
them with Checkov, for every starter, with no Google Cloud project. The first apply is yours.

## What it creates

- A service account of the app's own (never the project's default compute account).
<!-- @if service -->
- A Cloud Run service with one instance (the agent's state database has one writer), reached through your load
  balancer (`ingress`; never straight from the internet).
<!-- @end -->
<!-- @if job -->
- A Cloud Run job, which runs only when someone executes it. It runs the image's own command; by default the gold set
  against the offline stub.
<!-- @end -->
<!-- @if gateway -->
- The model gateway (LiteLLM) as a sidecar in the service; the agent starts after it, reaches it on localhost and
  holds only the gateway's key. The gateway calls Claude and gpt-oss-120b on Gemini Enterprise Agent Platform with the
  service account (Vertex AI User on the project): no model key exists.
- Four secrets in Secret Manager, with no version, each readable by the service account only.

## Where each model call goes

__MODEL_TABLE__

Claude is called at `vertex_location` (`global` by default, which promises no data residency; a multi-region or
regional location keeps it where the data residency page says). The names, fallbacks and budgets are in
`gateway/litellm.yaml`, built into the gateway image.
<!-- @end -->

## Before the first apply

These are one person's steps, once.

1. Build this project's image from its Dockerfile and push it to Artifact Registry by release tag.
<!-- @if gateway -->
   Build the gateway image from `gateway/` here and push it the same way. In Model Garden, enable Claude Sonnet 5.5,
   Claude Haiku 5.5 and gpt-oss-120b for the project.
<!-- @end -->
2. Copy `terraform.tfvars.example` to `terraform.tfvars` (git ignores it) and fill it in.
3. Apply once with `start_app = false`: it creates the service account and the secrets, and starts nothing.
<!-- @if gateway -->
4. In the Secret Manager console, add a version to each secret:

| Secret | What it holds | Read by |
|---|---|---|
| `__SLUG__-gateway-key` | The gateway's own key: long and random | the agent and the gateway |
| `__SLUG__-langfuse-public-key`, `__SLUG__-langfuse-secret-key` | Your Langfuse project's keys | the gateway |
| `__SLUG__-otel-headers` | `Authorization=Basic%20` followed by the base64 of `public key:secret key` | the agent |
<!-- @end -->
5. Set `start_app = true` and apply again, through your own pipeline, with its approvals. Put your load balancer, with
   TLS, in front of the service.

## How it was checked

`tofu validate`, then `tofu test` (tests/plan.tftest.hcl) plans it with the Google provider mocked and checks what
matters here: the app's own service account, no ingress straight from the internet, one instance, the agent starting
after the gateway, no provider key in the agent's container, the gateway key from Secret Manager, the models by IAM,
and the first apply starting nothing. Checkov scans the files. None of it reaches Google Cloud. Each fact about the
cloud has its source and the day it was checked (`qz cloud show gcp`; `qz cloud check` flags one older than 90 days).

## What it does not do

- Nobody has applied it. Your first apply, and the gateway's first live call to Agent Platform, prove it.
- The agent's state database is on the instance's own disk: a new instance starts with none, so a run waiting for a
  person is lost. One instance runs at a time. Several need the Postgres step-up.
- The audit lines go to Cloud Logging (`AGENT_AUDIT_LOG=-`); each instance starts its own hash chain.
<!-- @if gateway -->
- The agent checks each caller's OIDC token itself, so the service turns off Cloud Run's own IAM check
  (`invoker_iam_disabled`); the load balancer and your identity provider are the way in. Identity-Aware Proxy signs
  its header with ES256, and the agent reads RS256 bearer tokens, so put your OIDC provider in front, not IAP's header.
- Both containers act as the service account; the agent's own allow-list keeps its calls on the gateway.
- A budget counts only when the gateway knows the model's price: from the price list inside the pinned image, or
  `input_cost_per_token` and `output_cost_per_token` on the model in `gateway/litellm.yaml`. Check its spend on the first day.
<!-- @end -->
- Traces go to Langfuse. For Cloud Trace, run the Google-Built OpenTelemetry Collector as one more sidecar and point
  the agent's `OTEL_EXPORTER_OTLP_ENDPOINT` at it.
