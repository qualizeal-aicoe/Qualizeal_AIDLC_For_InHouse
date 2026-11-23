# __NAME__ on Azure

`qz cloud add azure` wrote this folder for __NAME__ (__STACK__): __SHAPE__. It is OpenTofu, which Terraform also
reads. Nobody has applied it. The Studio's CI validates these files, plans them with the providers mocked and scans
them with Checkov, for every starter, with no Azure subscription. The first apply is yours.

## What it creates

- A resource group, Log Analytics for the logs, a user-assigned managed identity, and a Key Vault with RBAC and purge
  protection: the identity may read its keys (Key Vault Secrets User), and `secret_writers` may set them.
- A Container Apps environment.
<!-- @if service -->
- A container app with one replica (the agent's state database has one writer), reached only inside its environment
  unless `public` (then only from `allowed_ips`). Put your front door, with TLS, in front of it.
<!-- @end -->
<!-- @if job -->
- A Container Apps job, started by hand. It runs the image's own command; by default the gold set against the offline
  stub.
<!-- @end -->
<!-- @if gateway -->
- The model gateway (LiteLLM) as a second container in the app. The agent reaches it on localhost and holds only the
  gateway's key; the Foundry key reaches the gateway's container only.
- A Microsoft Foundry resource with a project, Claude Sonnet 5.5 and Haiku 5.5 deployed in it (version
  `claude_model_version`, Global Standard), and gpt-oss-120b, sold by Azure, as the open-weight fallback.

## Where each model call goes

__MODEL_TABLE__

The names, fallbacks and budgets are in `gateway/litellm.yaml`, built into the gateway image.

## Anthropic's terms

Deploying Claude in Foundry accepts Anthropic's terms through the Azure Marketplace, with the organization, country
and industry you give (`claude_organization_name`, `claude_country_code`, `claude_industry`). They have no default
here, and the plan stops without them: your administrator decides to accept, and the subscription needs permission to
subscribe to Marketplace offers. The deployments go through the azapi provider because azurerm does not take those
details yet; Microsoft's own sample (github.com/Azure-Samples/claude) deploys Claude the same way.
<!-- @end -->

## Before the first apply

These are one person's steps, once.

1. Build this project's image from its Dockerfile and push it to your registry by release tag; give `registry_server`
   and `acr_id` so the app's identity can pull it.
<!-- @if gateway -->
   Build the gateway image from `gateway/` here and push it the same way.
<!-- @end -->
2. Copy `terraform.tfvars.example` to `terraform.tfvars` (git ignores it) and fill it in, with your own object ID in
   `secret_writers`.
3. Apply once with `start_app = false`: it creates the vault, the identity and the environment
<!-- @if gateway -->
   and the Foundry models,
<!-- @end -->
   and starts nothing.
<!-- @if gateway -->
4. In Key Vault, create each secret:

| Secret | What it holds | Read by |
|---|---|---|
| `__SLUG__-gateway-key` | The gateway's own key: long and random | the agent and the gateway |
| `__SLUG__-foundry-key` | The Foundry resource's key (in the portal: the resource, Keys and Endpoint) | the gateway |
| `__SLUG__-langfuse-public-key`, `__SLUG__-langfuse-secret-key` | Your Langfuse project's keys | the gateway |
| `__SLUG__-otel-headers` | `Authorization=Basic%20` followed by the base64 of `public key:secret key` | the agent |
<!-- @end -->
5. Set `start_app = true` and apply again, through your own pipeline, with its approvals.

## How it was checked

`tofu validate`, then `tofu test` (tests/plan.tftest.hcl) plans it with the providers mocked and checks what matters
here: the vault on RBAC with purge protection, read-only access for the app's identity, one replica, no public
ingress by default and 0.0.0.0/0 refused, no provider key in the agent's container, every key a Key Vault reference
with no value, Claude deployed with the client's own details, the plan stopping without them, and the first apply
starting nothing. Checkov scans the files. None of it reaches Azure. Each fact about the cloud has its source and the
day it was checked (`qz cloud show azure`; `qz cloud check` flags one older than 90 days).

## What it does not do

- Nobody has applied it. Your first apply, and the gateway's first live call to Foundry, prove it.
- The agent's state database is on the replica's own disk: a new revision or a restart starts with none, so a run
  waiting for a person is lost. One replica runs at a time. Several need the Postgres step-up.
- The audit lines go to Log Analytics (`AGENT_AUDIT_LOG=-`); each replica starts its own hash chain.
<!-- @if gateway -->
- The gateway calls Foundry with the resource's key, kept in Key Vault: LiteLLM's Foundry route takes a key or a
  service principal's secret, not the app's managed identity. So Foundry keeps local keys on (`local_auth_enabled`).
- Both containers can use the app's managed identity, which may read the app's secrets in Key Vault, the Foundry key
  among them. The agent's own allow-list keeps its calls on the gateway, but the identity is the app's, not the
  gateway's alone.
- Key Vault and Foundry are reached over their public endpoints, with RBAC and keys on every call. Inside your virtual
  network with private endpoints, set `key_vault_public = false` and `foundry_public = false`.
- A budget counts only when the gateway knows the model's price: from the price list inside the pinned image, or
  `input_cost_per_token` and `output_cost_per_token` on the model in `gateway/litellm.yaml`. Check its spend on the first day.
<!-- @end -->
- Traces go to Langfuse. For Application Insights, run an OpenTelemetry Collector with OTLP into Azure Monitor and
  point the agent's `OTEL_EXPORTER_OTLP_ENDPOINT` at it.
