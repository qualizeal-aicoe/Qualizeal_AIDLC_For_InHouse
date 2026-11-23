variable "kubeconfig_path" {
  description = "The kubeconfig of the person or pipeline that applies this."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "The kubeconfig context to use; null takes the current one."
  type        = string
  default     = null
}

variable "namespace" {
  description = "The namespace for this app; null names it after the project."
  type        = string
  default     = null
}

variable "agent_image" {
  description = "The image built from this project's Dockerfile, by release tag or, stronger, by digest (never latest)."
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

variable "image_pull_secret" {
  description = "The Secret that lets the cluster pull from a private registry; empty for none."
  type        = string
  default     = ""
}

variable "secret_store" {
  description = "The ClusterSecretStore the cluster's administrator set up for External Secrets Operator (AWS Secrets Manager, Azure Key Vault, Google Secret Manager or OpenBao)."
  type        = string
  default     = "cloud-secrets"
}

variable "secret_prefix" {
  description = "The prefix of this app's key names in the secret store; null uses the project's name. A person puts each value there; nothing here holds one."
  type        = string
  default     = null
}

variable "oidc_issuer" {
  description = "The client's OIDC issuer URL: the agent checks every caller's token against it (AGENT_IDENTITY=oidc)."
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
  description = "The Langfuse the agent sends its run traces to and the gateway its record of each model call, such as https://langfuse.example.com (self-hosted or cloud). Agent starters only."
  type        = string
  default     = ""
}

variable "storage_class" {
  description = "The storage class for the agent's state volume; null takes the cluster's default."
  type        = string
  default     = null
}

variable "state_size" {
  description = "The size of the agent's state volume (its runs and the changes its tools made)."
  type        = string
  default     = "1Gi"
}

variable "ingress_namespaces" {
  description = "Namespaces whose pods may reach the app's port (such as the ingress controller's); its own namespace always may."
  type        = list(string)
  default     = []
}

variable "job_schedule" {
  description = "For a project that runs to completion: when the job runs. It starts suspended, so it runs only when someone starts it."
  type        = string
  default     = "0 3 * * *"
}

variable "job_suspended" {
  description = "Keep the job's schedule off; start a run by hand from the CronJob."
  type        = bool
  default     = true
}

variable "sie_enabled" {
  description = "Install SIE in the cluster for the open models (the gateway's fallback); null installs it for an agent and not for the others. Its larger models need GPU nodes."
  type        = bool
  default     = null
}

variable "sie_namespace" {
  description = "The namespace for SIE."
  type        = string
  default     = "sie"
}

variable "sie_extra_values" {
  description = "More values for SIE's chart (YAML strings), such as its values-gke.yaml or values-aws.yaml. They may not touch telemetry or authentication."
  type        = list(string)
  default     = []
  validation {
    condition = alltrue([for v in var.sie_extra_values : !can(yamldecode(v).telemetry) && !can(yamldecode(v).gateway.auth) && !can(yamldecode(v).workers.auth) && !can(yamldecode(v).workers.networkPolicy)])
    error_message = "sie_extra_values may not set telemetry, gateway.auth, workers.auth or workers.networkPolicy: sie-values.yaml holds those, switched to their safe values."
  }
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
    agent_cpu      = "500m"
    agent_memory   = "1Gi"
    gateway_cpu    = "250m"
    gateway_memory = "768Mi"
  }
}
