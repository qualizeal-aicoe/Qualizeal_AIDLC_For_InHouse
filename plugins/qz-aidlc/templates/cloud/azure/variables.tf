variable "subscription_id" {
  description = "The client's Azure subscription."
  type        = string
}

variable "location" {
  description = "The Azure region for the app, its Key Vault and its logs."
  type        = string
  default     = "eastus2"
}

variable "foundry_location" {
  description = "The region of the Foundry resource that serves Claude: one where Claude's Global Standard deployments are offered (see the Foundry model catalog), such as eastus2 or swedencentral."
  type        = string
  default     = "eastus2"
}

variable "agent_image" {
  description = "The image built from this project's Dockerfile, in the client's registry, by release tag or, stronger, by digest (never latest)."
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

variable "registry_server" {
  description = "The client's container registry, such as example.azurecr.io; the app pulls from it with its managed identity. Empty for a public registry."
  type        = string
  default     = ""
}

variable "acr_id" {
  description = "The registry's resource ID, so the app's identity is given AcrPull on it; null if someone grants that separately."
  type        = string
  default     = null
}

variable "start_app" {
  description = "false for the first apply (the vault, the identity, the Foundry models); true once a person has put each key's value in Key Vault."
  type        = bool
  default     = false
}

variable "secret_writers" {
  description = "Object IDs of the people (or group) who put the keys' values in Key Vault: they are given Key Vault Secrets Officer on this vault."
  type        = list(string)
  default     = []
}

variable "public" {
  description = "Let the app be reached from outside its Container Apps environment. Off by default: put the client's front door (with TLS and the allowed_ips) first."
  type        = bool
  default     = false
}

variable "allowed_ips" {
  description = "When public, the address ranges that may reach the app (CIDR blocks)."
  type        = list(string)
  default     = []
  validation {
    condition     = !contains(var.allowed_ips, "0.0.0.0/0")
    error_message = "Not the whole internet: name the client's address ranges or put a front door in front."
  }
}

variable "key_vault_public" {
  description = "Reach Key Vault over its public endpoint (with RBAC on every call). Set false once the environment is in the client's virtual network with a private endpoint for the vault."
  type        = bool
  default     = true
}

variable "foundry_public" {
  description = "Reach Foundry over its public endpoint. Set false once the environment is in the client's virtual network with a private endpoint for Foundry."
  type        = bool
  default     = true
}

variable "oidc_issuer" {
  description = "The client's OIDC issuer URL (Entra ID: https://login.microsoftonline.com/<tenant>/v2.0): the agent checks every caller's token against it."
  type        = string
  default     = ""
}

variable "oidc_audience" {
  description = "The audience the agent expects in the tokens (the app registration's client ID or its Application ID URI)."
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

variable "claude_organization_name" {
  description = "The client's organization, as Anthropic's terms through the Azure Marketplace need it. Applying the Claude deployments accepts those terms for the client: the client's administrator decides that."
  type        = string
  default     = ""
}

variable "claude_country_code" {
  description = "The client's two-letter country code, for the same terms."
  type        = string
  default     = ""
}

variable "claude_industry" {
  description = "The client's industry, in lower case as the Foundry portal lists it (technology, finance, healthcare, education, retail, manufacturing, government, media, other)."
  type        = string
  default     = ""
}

variable "claude_model_version" {
  description = "The Claude model version to deploy; version 2 of Sonnet 5.5 and Haiku 5.5 is hosted on Azure (Foundry model catalog)."
  type        = string
  default     = "2"
}

variable "capacity" {
  description = "Each deployment's capacity (thousands of tokens per minute)."
  type = object({
    claude       = number
    claude_small = number
    open         = number
  })
  default = {
    claude       = 25
    claude_small = 25
    open         = 10
  }
}

variable "log_retention_days" {
  description = "How long the app's logs (its audit lines among them) are kept in Log Analytics."
  type        = number
  default     = 90
}
