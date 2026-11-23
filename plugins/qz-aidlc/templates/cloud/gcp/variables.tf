variable "project_id" {
  description = "The client's Google Cloud project."
  type        = string
}

variable "region" {
  description = "The Region for the app."
  type        = string
  default     = "us-central1"
}

variable "vertex_location" {
  description = "Where the gateway calls Claude on Gemini Enterprise Agent Platform: global (no residency guarantee), or a multi-region or regional location the data residency page lists for the model."
  type        = string
  default     = "global"
}

variable "agent_image" {
  description = "The image built from this project's Dockerfile, in the client's registry (Artifact Registry), by release tag or, stronger, by digest (never latest)."
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
  description = "false for the first apply (the keys' entries in Secret Manager, the service account); true once a person has added each key's value as a version in Secret Manager."
  type        = bool
  default     = false
}

variable "ingress" {
  description = "Who may reach the service: through a load balancer (the default, so TLS and the client's front door come first) or from inside the VPC only."
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  validation {
    condition     = contains(["INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER", "INGRESS_TRAFFIC_INTERNAL_ONLY"], var.ingress)
    error_message = "Not INGRESS_TRAFFIC_ALL: put the client's load balancer in front."
  }
}

variable "deletion_protection" {
  description = "Refuse to destroy the service or the job by accident."
  type        = bool
  default     = true
}

variable "oidc_issuer" {
  description = "The client's OIDC issuer URL: the agent checks every caller's RS256 token against it."
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

variable "kms_key" {
  description = "The client's Cloud KMS key for the secrets (projects/.../cryptoKeys/...); null uses Google-managed encryption."
  type        = string
  default     = null
}

variable "resources" {
  description = "CPU and memory for each container."
  type = object({
    agent_cpu      = string
    agent_memory   = string
    gateway_cpu    = string
    gateway_memory = string
  })
  default = {
    agent_cpu      = "1"
    agent_memory   = "1Gi"
    gateway_cpu    = "1"
    gateway_memory = "1Gi"
  }
}
