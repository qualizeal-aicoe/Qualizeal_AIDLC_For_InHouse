variable "region" {
  description = "The AWS Region for the app (and the source Region of its Bedrock calls)."
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "The client's VPC."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the app's task: no public address. They reach Bedrock through a NAT gateway or VPC endpoints."
  type        = list(string)
  validation {
    condition     = length(var.subnet_ids) > 0
    error_message = "Give at least one private subnet."
  }
}

variable "allowed_cidrs" {
  description = "Who may reach the app's port: the client's load balancer or network, as CIDR blocks. Empty lets nothing in."
  type        = list(string)
  default     = []
  validation {
    condition     = !contains(var.allowed_cidrs, "0.0.0.0/0")
    error_message = "Not the whole internet: put a load balancer with TLS in front and allow its subnets."
  }
}

variable "target_group_arn" {
  description = "An existing load balancer target group (type ip) to register the app in; null for none."
  type        = string
  default     = null
}

variable "agent_image" {
  description = "The image built from this project's Dockerfile, in the client's registry (ECR), by release tag or, stronger, by digest (never latest)."
  type        = string
  validation {
    condition     = can(regex("(:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}|@sha256:[0-9a-f]{64})$", var.agent_image)) && !can(regex(":latest(@sha256:[0-9a-f]{64})?$", var.agent_image)) && !can(regex("\\s", var.agent_image))
    error_message = "Name the image by release tag or digest (registry/name:1.4.0, or @sha256:...), never latest or no tag: a rollback is the previous tag."
  }
}

variable "gateway_image" {
  description = "The image built from gateway/Dockerfile here (LiteLLM with this cloud's model list). Agent starters only."
  type        = string
  default     = ""
  validation {
    condition     = var.gateway_image == "" || (can(regex("(:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}|@sha256:[0-9a-f]{64})$", var.gateway_image)) && !can(regex(":latest(@sha256:[0-9a-f]{64})?$", var.gateway_image)) && !can(regex("\\s", var.gateway_image)))
    error_message = "Name the gateway image by release tag or digest, never latest or no tag."
  }
}

variable "start_app" {
  description = "false for the first apply (the keys' entries in Secrets Manager, the roles, the cluster); true once a person has put each key's value in Secrets Manager."
  type        = bool
  default     = false
}

variable "oidc_issuer" {
  description = "The client's OIDC issuer URL (Cognito, Entra ID, Okta, Keycloak): the agent checks every caller's token against it."
  type        = string
  default     = ""
}

variable "oidc_audience" {
  description = "The audience the agent expects in the tokens."
  type        = string
  default     = ""
}

variable "oidc_jwks_url" {
  description = "The issuer's key set URL; empty lets the agent find it from the issuer."
  type        = string
  default     = ""
}

variable "langfuse_host" {
  description = "The Langfuse the agent sends its run traces to and the gateway its record of each model call, such as https://langfuse.example.com. Agent starters only."
  type        = string
  default     = ""
}

variable "kms_key_arn" {
  description = "The client's KMS key for the logs and the secrets; null uses AWS-managed encryption."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "How long the app's logs (its audit lines among them) are kept."
  type        = number
  default     = 365
}

variable "cpu" {
  description = "The task's CPU units."
  type        = number
  default     = 1024
}

variable "memory" {
  description = "The task's memory in MiB."
  type        = number
  default     = 2048
}
