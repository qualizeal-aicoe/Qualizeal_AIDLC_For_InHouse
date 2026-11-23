# __NAME__ on Kubernetes

`qz cloud add kubernetes` wrote this folder for __NAME__ (__STACK__): __SHAPE__. It is OpenTofu, which Terraform
also reads. Nobody has applied it. The Studio's CI validates these files, plans them with the providers mocked and
scans them with Checkov, for every starter, with no cluster. The first apply is yours.

## What it creates

- A namespace that enforces the restricted pod security standard, a service account with no API token, and a network
  policy: the app's own namespace (and `ingress_namespaces`) may reach its port; it may reach DNS, SIE and HTTPS.
<!-- @if service -->
- A Deployment with one replica, replaced rather than doubled (the agent's state database has one writer), its state
  on a volume (`/data`), and a ClusterIP Service. Put your ingress, with TLS, in front of it.
<!-- @end -->
<!-- @if job -->
- A CronJob that starts suspended: it runs the image's own command only when someone starts a run from it (or turns
  its schedule on). By default that command is the gold set against the offline stub.
<!-- @end -->
<!-- @if gateway -->
- The model gateway (LiteLLM) as a second container in the agent's pod. The agent reaches it on localhost and holds
  only the gateway's key. The provider keys reach the gateway's container only.
- Two ExternalSecrets: External Secrets Operator copies the keys from your cloud's secret store into the pod.
- SIE, from its Helm chart (`sie.tf`), for the open-weight model the gateway falls back to. Its telemetry is off, its
  gateway and its workers ask for tokens, and its gateway token comes from your secret store (`sie-values.yaml`).
  `qz cloud lint` fails the Studio's CI if any of those goes back to the chart's default.

## Where each model call goes

__MODEL_TABLE__

The names, fallbacks and budgets are in `gateway/litellm.yaml`, built into the gateway image.
<!-- @end -->

## Before the first apply

These are one person's steps, once.

1. The cluster needs External Secrets Operator and a ClusterSecretStore for your secret store (AWS Secrets Manager,
   Azure Key Vault, Google Secret Manager or OpenBao); set `secret_store` to its name.
<!-- @if gateway -->
   SIE's larger models need GPU nodes. SIE's Terraform modules create a GPU cluster on EKS, AKS, GKE or ACK
   (`github.com/superlinked/terraform-aws-sie`, `terraform-azure-sie`, `terraform-google-sie`, `terraform-alicloud-sie`).
<!-- @end -->
2. Build this project's image from its Dockerfile and push it to your registry by release tag.
<!-- @if gateway -->
   Build the gateway image from `gateway/` here and push it the same way.
3. Put each key in your secret store, under these names (`secret_prefix` changes the prefix):

| Key | What it holds | Read by |
|---|---|---|
| `__SLUG__-gateway-key` | The gateway's own key: long and random, 32 characters or more | the agent and the gateway |
| `__SLUG__-anthropic-api-key` | Your Claude API key | the gateway |
| `__SLUG__-sie-token` | SIE's gateway token: long and random, 32 characters or more | SIE and the gateway |
| `__SLUG__-langfuse-public-key`, `__SLUG__-langfuse-secret-key` | Your Langfuse project's keys | the gateway |
| `__SLUG__-otel-headers` | `Authorization=Basic%20` followed by the base64 of `public key:secret key` | the agent |
<!-- @end -->
4. Copy `terraform.tfvars.example` to `terraform.tfvars` (git ignores it) and fill it in.
5. `tofu init`, `tofu test`, `tofu plan`, then apply through your own pipeline, with its approvals.

## How it was checked

`tofu validate`, then `tofu test` (tests/plan.tftest.hcl) plans it with the Kubernetes and Helm providers mocked and
checks what matters here: the restricted namespace, no API token in the pod, every container non-root with no
capabilities, one replica, no provider key in the agent's container, the keys from the secret store, SIE's telemetry
off and its tokens on, and that extra SIE values cannot turn telemetry or authentication back on. Checkov scans the
files. None of it reaches a cluster. Each fact about the cloud has its source and the day it was checked
(`qz cloud show kubernetes`; `qz cloud check` flags one older than 90 days).

## What it does not do

- Nobody has applied it. Your first apply, and the gateway's first live call, prove it against your cluster.
<!-- @if gateway -->
- The ExternalSecrets need External Secrets Operator's resources in the cluster when you plan for real: the mocked
  test does not need them, `tofu plan` against your cluster does.
- A budget counts only when the gateway knows the model's price: from the price list inside the pinned image, or
  `input_cost_per_token` and `output_cost_per_token` on the model in `gateway/litellm.yaml`. Check its spend on the first day.
- If SIE is off (`sie_enabled = false`), the gateway's fallback has nowhere to go: point `agent-model-fallback` in
  `gateway/litellm.yaml` at another model, and build the image again.
<!-- @end -->
- The containers' root filesystems are writable: the Claude Agent SDK, Node and some Python libraries write under
  HOME at run time. Making them read-only is a per-starter change, tested with the image.
- Traces go to Langfuse. To use your cloud's own trace service instead, run an OpenTelemetry Collector and point the
  agent's `OTEL_EXPORTER_OTLP_ENDPOINT` at it, and take the `langfuse_otel` callback out of `gateway/litellm.yaml`.
