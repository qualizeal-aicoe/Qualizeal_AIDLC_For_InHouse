# __NAME__ on AWS

`qz cloud add aws` wrote this folder for __NAME__ (__STACK__): __SHAPE__. It is OpenTofu, which Terraform also reads.
Nobody has applied it. The Studio's CI validates these files, plans them with the AWS provider mocked and scans them
with Checkov, for every starter, with no AWS account. The first apply is yours.

## What it creates

- An ECS cluster on Fargate and a task definition. Its containers run as a user, unprivileged, with every Linux
  capability dropped; its logs go to CloudWatch for a year (`log_retention_days`).
- Two IAM roles: the execution role starts the task (images, logs, the keys' values); the task role is what the
  containers act as.
- A security group: in, only `allowed_cidrs` on the app's port (never 0.0.0.0/0); out, HTTPS only.
<!-- @if service -->
- An ECS service with one task and no public address, replaced rather than doubled (the agent's state database has one
  writer). Give it `target_group_arn` to sit behind your load balancer, with TLS.
<!-- @end -->
<!-- @if job -->
- No service: a job is started from the task definition (`outputs.task_definition`), in your subnets, with the
  security group (`outputs.security_group_id`). It runs the image's own command; by default the gold set against the
  offline stub.
<!-- @end -->
<!-- @if gateway -->
- The model gateway (LiteLLM) as a second container in the task. The agent reaches it on localhost and holds only the
  gateway's key. The gateway calls Amazon Bedrock with the task role, which may invoke exactly the models below.
- Four entries in Secrets Manager, with no value.

## Where each model call goes

__MODEL_TABLE__

Claude is called through the `__GEO__.` inference profile (`qz cloud add aws --geo us|eu|global` chose it): `us.` and
`eu.` keep the data in that geography, `global.` routes it anywhere. gpt-oss-120b runs in your Region. The names,
fallbacks and budgets are in `gateway/litellm.yaml`, built into the gateway image.
<!-- @end -->

## Before the first apply

These are one person's steps, once.

1. Build this project's image from its Dockerfile and push it to ECR by release tag.
<!-- @if gateway -->
   Build the gateway image from `gateway/` here and push it the same way. In the Bedrock console, make sure your
   account can use the models above in your Region.
<!-- @end -->
2. Copy `terraform.tfvars.example` to `terraform.tfvars` (git ignores it) and fill it in: your VPC, private subnets
   that reach Bedrock (through a NAT gateway or VPC endpoints), and who may reach the app.
3. Apply once with `start_app = false`: it creates the roles, the cluster and the keys' entries, and starts nothing.
<!-- @if gateway -->
4. In the Secrets Manager console, set each entry's value:

| Entry | What it holds | Read by |
|---|---|---|
| `__SLUG__/gateway-key` | The gateway's own key: long and random | the agent and the gateway |
| `__SLUG__/langfuse-public-key`, `__SLUG__/langfuse-secret-key` | Your Langfuse project's keys | the gateway |
| `__SLUG__/otel-headers` | `Authorization=Basic%20` followed by the base64 of `public key:secret key` | the agent |

   There is no model key: the gateway reaches Bedrock with the task role.
<!-- @end -->
5. Set `start_app = true` and apply again, through your own pipeline, with its approvals.

## How it was checked

`tofu validate`, then `tofu test` (tests/plan.tftest.hcl) plans it with the AWS provider mocked and checks what matters
here: Fargate in awsvpc mode, separate execution and task roles, every container non-root and unprivileged, logs kept
a year, no public address, no provider key in the agent's container, the gateway key from Secrets Manager, the task
role limited to the gateway's Bedrock models, the first apply starting nothing, and 0.0.0.0/0 refused. Checkov scans
the files. None of it reaches AWS. Each fact about the cloud has its source and the day it was checked
(`qz cloud show aws`; `qz cloud check` flags one older than 90 days).

## What it does not do

- Nobody has applied it. Your first apply, and the gateway's first live call to Bedrock, prove it against your account.
- The agent's state database is on the task's own disk: a new task (a deploy, a crash) starts with none, so a run
  waiting for a person is lost. One task runs at a time. Several tasks need the Postgres step-up.
- The audit lines go to CloudWatch Logs (`AGENT_AUDIT_LOG=-`); each task starts its own hash chain.
<!-- @if gateway -->
- Both containers act as the task role. It may invoke only the gateway's models, and the agent's own allow-list keeps
  its calls on the gateway, but the role is the task's, not the gateway's alone.
- A budget counts only when the gateway knows the model's price: from the price list inside the pinned image, or
  `input_cost_per_token` and `output_cost_per_token` on the model in `gateway/litellm.yaml`. Check its spend on the first day.
<!-- @end -->
- The containers' root filesystems are writable (some starters write under HOME at run time).
- Traces go to Langfuse. CloudWatch's OTLP endpoint wants SigV4-signed calls, so using it means adding the AWS Distro
  for OpenTelemetry collector as a third container and pointing the agent's `OTEL_EXPORTER_OTLP_ENDPOINT` at it.
