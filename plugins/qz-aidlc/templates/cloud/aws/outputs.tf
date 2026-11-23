output "keys_to_set" {
  description = "The Secrets Manager entries a person fills in before setting start_app = true. Nothing here holds a value."
  value       = sort([for k in local.key_names : aws_secretsmanager_secret.keys[k].name])
}

output "cluster" {
  description = "The ECS cluster."
  value       = aws_ecs_cluster.app.name
}

output "task_definition" {
  description = "The task definition: a job is started from it (with the subnets and the security group below)."
  value       = aws_ecs_task_definition.app.arn
}

output "security_group_id" {
  description = "The app's security group."
  value       = aws_security_group.app.id
}

output "bedrock_models" {
  description = "The Bedrock resources the task role may invoke."
  value       = local.model_arns
}
