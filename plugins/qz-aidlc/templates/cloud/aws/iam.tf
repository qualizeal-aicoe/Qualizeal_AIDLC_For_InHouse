# Two roles, each with only what it needs. The execution role starts the task: it pulls the images, writes the logs
# and reads the keys' values from Secrets Manager. The task role is what the containers act as: for an agent, it may
# invoke the Bedrock models the gateway names and nothing else. Both containers of a task share the task role, so the
# agent's own allow-list is what keeps its calls on the gateway.

locals {
  account = data.aws_caller_identity.this.account_id
  arn     = "arn:${data.aws_partition.this.partition}"
  bedrock = {
    "claude"       = "anthropic.claude-sonnet-5-5"
    "claude-small" = "anthropic.claude-haiku-5-5"
    "open"         = "openai.gpt-oss-120b-1:0"
  }
  # Claude is reached only through an inference profile (us., eu. or global.); the open model in-Region.
  claude_ids = [for r in local.s.models : local.bedrock[r] if r != "open"]
  model_arns = concat(
    [for id in local.claude_ids : "${local.arn}:bedrock:${var.region}:${local.account}:inference-profile/${local.s.geo}.${id}"],
    [for id in local.claude_ids : "${local.arn}:bedrock:*::foundation-model/${id}"],
    local.s.geo == "global" ? [for id in local.claude_ids : "${local.arn}:bedrock:::foundation-model/${id}"] : [],
    contains(local.s.models, "open") ? ["${local.arn}:bedrock:${var.region}::foundation-model/${local.bedrock["open"]}"] : [],
  )

  ecs_tasks_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Condition = { StringEquals = { "aws:SourceAccount" = local.account } }
    }]
  })
  read_keys = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [{ Sid = "ReadThisAppsKeys", Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [for k in local.key_names : aws_secretsmanager_secret.keys[k].arn] }],
      var.kms_key_arn == null ? [] : [{ Sid = "DecryptThem", Effect = "Allow", Action = ["kms:Decrypt"], Resource = [var.kms_key_arn] }],
    )
  })
  invoke_models = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Sid = "InvokeTheGatewaysModels", Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], Resource = local.model_arns }]
  })
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = local.ecs_tasks_trust
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "${local.arn}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "read_keys" {
  count  = length(local.key_names) > 0 ? 1 : 0
  name   = "read-keys"
  role   = aws_iam_role.execution.id
  policy = local.read_keys
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = local.ecs_tasks_trust
}

resource "aws_iam_role_policy" "bedrock" {
  count  = local.gateway ? 1 : 0
  name   = "bedrock-invoke"
  role   = aws_iam_role.task.id
  policy = local.invoke_models
}
