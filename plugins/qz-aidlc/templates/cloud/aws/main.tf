# This project on Amazon ECS (Fargate): one task holding the app and, for an agent, the model gateway beside it (the
# two talk over localhost), its keys named in Secrets Manager, its logs in CloudWatch, a security group that lets in
# only the client's network. The gateway reaches Claude and the open-weight model on Amazon Bedrock with the task's
# role (iam.tf): no model key exists. What the project is (an HTTP service or a job) comes from starter.tf.

data "aws_caller_identity" "this" {}
data "aws_partition" "this" {}

locals {
  s       = local.starter
  service = local.s.shape == "service"
  gateway = local.s.gateway
  name    = local.s.slug

  # Each key this app reads: its environment variable, and its entry in Secrets Manager. A person puts the values
  # in; nothing here holds one. Provider keys: none on AWS, the gateway calls Bedrock with the task's role.
  agent_keys   = local.gateway ? { AGENT_GATEWAY_KEY = "gateway-key", OTEL_EXPORTER_OTLP_HEADERS = "otel-headers" } : {}
  gateway_keys = local.gateway ? { LITELLM_MASTER_KEY = "gateway-key", LANGFUSE_PUBLIC_KEY = "langfuse-public-key", LANGFUSE_SECRET_KEY = "langfuse-secret-key" } : {}
  key_names    = toset(concat(values(local.agent_keys), values(local.gateway_keys)))

  log = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.app.name, "awslogs-region" = var.region } }

  agent_env = local.gateway ? {
    AGENT_MODE                  = "live"
    APP_ENV                     = "production"
    AGENT_IDENTITY              = "oidc"
    AGENT_OIDC_ISSUER           = var.oidc_issuer
    AGENT_OIDC_AUDIENCE         = var.oidc_audience
    AGENT_OIDC_JWKS_URL         = var.oidc_jwks_url
    AGENT_GATEWAY               = "litellm"
    AGENT_GATEWAY_URL           = "http://127.0.0.1:4000"
    AGENT_AUDIT_LOG             = "-"
    OTEL_EXPORTER_OTLP_ENDPOINT = "${var.langfuse_host}/api/public/otel"
    OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
  } : { APP_ENV = "production" }

  app_container = merge({
    name                   = "app"
    image                  = var.agent_image
    essential              = true
    user                   = tostring(local.s.uid)
    privileged             = false
    readonlyRootFilesystem = false
    linuxParameters        = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }
    environment            = [for k, v in local.agent_env : { name = k, value = v }]
    secrets                = [for env, key in local.agent_keys : { name = env, valueFrom = aws_secretsmanager_secret.keys[key].arn }]
    logConfiguration       = merge(local.log, { options = merge(local.log.options, { "awslogs-stream-prefix" = "app" }) })
    },
    length(local.s.args) > 0 ? { command = local.s.args } : {},
    local.service ? { portMappings = [{ containerPort = local.s.port, protocol = "tcp" }] } : {},
    local.gateway ? { dependsOn = [{ containerName = "gateway", condition = "HEALTHY" }] } : {},
  )

  gateway_container = {
    name                   = "gateway"
    image                  = var.gateway_image
    essential              = true
    user                   = "65534"
    privileged             = false
    readonlyRootFilesystem = false
    linuxParameters        = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } }
    environment            = [{ name = "AWS_REGION", value = var.region }, { name = "LANGFUSE_HOST", value = var.langfuse_host }]
    secrets                = [for env, key in local.gateway_keys : { name = env, valueFrom = aws_secretsmanager_secret.keys[key].arn }]
    healthCheck = {
      command     = ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=4)"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = merge(local.log, { options = merge(local.log.options, { "awslogs-stream-prefix" = "gateway" }) })
  }
}

# The keys' entries, empty. A person puts each value in through the console (or their own pipeline) before start_app.
resource "aws_secretsmanager_secret" "keys" {
  # checkov:skip=CKV2_AWS_57:These are a gateway key and Langfuse keys a person sets and rotates at their source; rotation would need a function per source
  # checkov:skip=CKV_AWS_149:A customer-managed key is the client's choice (kms_key_arn); without one, Secrets Manager uses the AWS managed key
  for_each                = local.key_names
  name                    = "${local.name}/${each.key}"
  description             = "${each.key} for ${local.name}. Set its value here; nothing in OpenTofu holds it."
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 30
}

resource "aws_cloudwatch_log_group" "app" {
  # checkov:skip=CKV_AWS_158:A customer-managed key is the client's choice (kms_key_arn); without one, CloudWatch Logs encrypts with its own key
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_ecs_cluster" "app" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_security_group" "app" {
  # checkov:skip=CKV2_AWS_5:A service's ECS service uses this group; a job's is passed to aws ecs run-task (output security_group_id)
  name        = local.name
  description = "Who may reach ${local.name}, and what it may reach"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "app" {
  for_each          = local.service ? toset(var.allowed_cidrs) : toset([])
  security_group_id = aws_security_group.app.id
  description       = "The client's network or load balancer, to the app's port"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = local.s.port
  to_port           = local.s.port
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS out: Bedrock, Secrets Manager, the registry, logs, the identity provider, Langfuse"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_ecs_task_definition" "app" {
  # checkov:skip=CKV_AWS_336:Some starters write under HOME at run time; the README lists the writable root filesystem as a limit
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode(slice([local.app_container, local.gateway_container], 0, local.gateway ? 2 : 1))

  lifecycle {
    precondition {
      condition     = !local.gateway || (var.gateway_image != "" && var.oidc_issuer != "" && var.oidc_audience != "" && var.langfuse_host != "")
      error_message = "An agent needs gateway_image, oidc_issuer, oidc_audience and langfuse_host."
    }
  }
}

# An HTTP service: one task, replaced rather than doubled (its state database has one writer), with no public address.
resource "aws_ecs_service" "app" {
  count                              = local.service && var.start_app ? 1 : 0
  name                               = local.name
  cluster                            = aws_ecs_cluster.app.id
  task_definition                    = aws_ecs_task_definition.app.arn
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  desired_count                      = 1
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  enable_execute_command             = false
  propagate_tags                     = "SERVICE"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = var.target_group_arn == null ? [] : [var.target_group_arn]
    content {
      target_group_arn = load_balancer.value
      container_name   = "app"
      container_port   = local.s.port
    }
  }
}
