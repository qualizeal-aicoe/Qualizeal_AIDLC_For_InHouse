# This project on Azure Container Apps: one app holding the app and, for an agent, the model gateway beside it (the
# two share the app's network, so the agent reaches the gateway on localhost), its keys in Key Vault read through the
# app's own managed identity, its logs in Log Analytics. The models are in Foundry (foundry.tf, claude.tf). What the
# project is (an HTTP service or a job) comes from starter.tf.

data "azurerm_client_config" "this" {}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

locals {
  s       = local.starter
  service = local.s.shape == "service"
  gateway = local.s.gateway
  name    = local.s.slug
  short   = trimsuffix(substr(local.name, 0, 24), "-")
  vault   = "kv${substr(replace(local.name, "-", ""), 0, 14)}${random_string.suffix.result}"

  # Each key this app reads: its environment variable, and its name in Key Vault. A person puts the values in; nothing
  # here holds one. The Foundry key is the gateway's alone: LiteLLM's Foundry route takes a key, not a managed identity.
  agent_keys   = local.gateway ? { AGENT_GATEWAY_KEY = "gateway-key", OTEL_EXPORTER_OTLP_HEADERS = "otel-headers" } : {}
  gateway_keys = local.gateway ? { LITELLM_MASTER_KEY = "gateway-key", AZURE_AI_API_KEY = "foundry-key", LANGFUSE_PUBLIC_KEY = "langfuse-public-key", LANGFUSE_SECRET_KEY = "langfuse-secret-key" } : {}
  key_names    = toset(concat(values(local.agent_keys), values(local.gateway_keys)))

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
  gateway_env = local.gateway ? {
    AZURE_AI_API_BASE    = "https://${local.foundry_host}/anthropic"
    AZURE_OPENAI_V1_BASE = "https://${local.foundry_host}/openai/v1"
    LANGFUSE_HOST        = var.langfuse_host
  } : {}
}

resource "azurerm_resource_group" "app" {
  name     = "rg-${local.name}"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "app" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
}

resource "azurerm_key_vault" "app" {
  # checkov:skip=CKV_AZURE_109:Container Apps outside a virtual network reach the vault from changing addresses; RBAC guards every call. With a private endpoint, set key_vault_public = false
  # checkov:skip=CKV_AZURE_189:As above: public access is a variable, off once the environment has a private endpoint
  # checkov:skip=CKV2_AZURE_32:The private endpoint needs the client's virtual network and DNS zone, which this template does not own
  name                          = local.vault
  location                      = azurerm_resource_group.app.location
  resource_group_name           = azurerm_resource_group.app.name
  tenant_id                     = data.azurerm_client_config.this.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = var.key_vault_public
  network_acls {
    default_action = var.key_vault_public ? "Allow" : "Deny"
    bypass         = "AzureServices"
  }
}

resource "azurerm_role_assignment" "read_keys" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "write_keys" {
  for_each             = toset(var.secret_writers)
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "pull" {
  count                = var.acr_id == null ? 0 : 1
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_container_app_environment" "app" {
  name                       = "cae-${local.short}"
  location                   = azurerm_resource_group.app.location
  resource_group_name        = azurerm_resource_group.app.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.app.id
}

# An HTTP service: one replica (its state database has one writer), reached only inside its environment unless public.
resource "azurerm_container_app" "app" {
  count                        = local.service && var.start_app ? 1 : 0
  name                         = local.short
  container_app_environment_id = azurerm_container_app_environment.app.id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  dynamic "registry" {
    for_each = var.registry_server == "" ? [] : [var.registry_server]
    content {
      server   = registry.value
      identity = azurerm_user_assigned_identity.app.id
    }
  }

  dynamic "secret" {
    for_each = local.key_names
    content {
      name                = secret.value
      key_vault_secret_id = "${azurerm_key_vault.app.vault_uri}secrets/${local.name}-${secret.value}"
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  ingress {
    external_enabled           = var.public
    target_port                = local.s.port
    transport                  = "auto"
    allow_insecure_connections = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
    dynamic "ip_security_restriction" {
      for_each = var.public ? var.allowed_ips : []
      content {
        name             = "allowed-${ip_security_restriction.key}"
        action           = "Allow"
        ip_address_range = ip_security_restriction.value
      }
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "app"
      image  = var.agent_image
      args   = length(local.s.args) > 0 ? local.s.args : null
      cpu    = 0.5
      memory = "1Gi"
      dynamic "env" {
        for_each = local.agent_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.agent_keys
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      startup_probe {
        transport               = "HTTP"
        port                    = local.s.port
        path                    = local.s.health
        interval_seconds        = 5
        failure_count_threshold = 24
      }
      liveness_probe {
        transport        = "HTTP"
        port             = local.s.port
        path             = local.s.health
        interval_seconds = 30
      }
    }

    dynamic "container" {
      for_each = local.gateway ? ["gateway"] : []
      content {
        name   = "gateway"
        image  = var.gateway_image
        cpu    = 0.5
        memory = "1Gi"
        dynamic "env" {
          for_each = local.gateway_env
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.gateway_keys
          content {
            name        = env.key
            secret_name = env.value
          }
        }
        startup_probe {
          transport               = "HTTP"
          port                    = 4000
          path                    = "/health/liveliness"
          interval_seconds        = 5
          failure_count_threshold = 24
        }
      }
    }
  }

  depends_on = [azurerm_role_assignment.read_keys, azurerm_role_assignment.pull]

  lifecycle {
    precondition {
      condition     = !local.gateway || (var.gateway_image != "" && var.oidc_issuer != "" && var.oidc_audience != "" && var.langfuse_host != "")
      error_message = "An agent needs gateway_image, oidc_issuer, oidc_audience and langfuse_host."
    }
  }
}

# A project that runs to completion: a Container Apps job started by hand. It runs the image's own command.
resource "azurerm_container_app_job" "app" {
  count                        = local.service ? 0 : 1
  name                         = local.short
  location                     = azurerm_resource_group.app.location
  resource_group_name          = azurerm_resource_group.app.name
  container_app_environment_id = azurerm_container_app_environment.app.id
  replica_timeout_in_seconds   = 3600
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  dynamic "registry" {
    for_each = var.registry_server == "" ? [] : [var.registry_server]
    content {
      server   = registry.value
      identity = azurerm_user_assigned_identity.app.id
    }
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "app"
      image  = var.agent_image
      cpu    = 0.5
      memory = "1Gi"
      env {
        name  = "APP_ENV"
        value = "production"
      }
    }
  }

  depends_on = [azurerm_role_assignment.pull]
}
