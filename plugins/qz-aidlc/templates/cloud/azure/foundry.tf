# Microsoft Foundry, for an agent: one resource with a project, Claude deployed in it (claude.tf) and gpt-oss-120b,
# the open-weight fallback, sold by Azure. The gateway calls all three with the resource's key, which a person copies
# into Key Vault (README). Foundry's Claude endpoint is https://<resource>.services.ai.azure.com/anthropic.

locals {
  foundry_name = "${local.short}-${random_string.suffix.result}"
  foundry_host = "${local.foundry_name}.services.ai.azure.com"
}

resource "azurerm_cognitive_account" "foundry" {
  # checkov:skip=CKV_AZURE_236:The gateway (LiteLLM) calls Foundry with the resource's key, kept in Key Vault; its Foundry route takes a key or a service principal's secret, not a managed identity
  # checkov:skip=CKV_AZURE_134:Public access is a variable (foundry_public), off once the environment has a private endpoint in the client's network
  # checkov:skip=CKV2_AZURE_22:A customer-managed key needs the client's key in their own vault; add customer_managed_key when they choose one
  count                         = local.gateway ? 1 : 0
  name                          = local.foundry_name
  location                      = var.foundry_location
  resource_group_name           = azurerm_resource_group.app.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = local.foundry_name
  project_management_enabled    = true
  local_auth_enabled            = true
  public_network_access_enabled = var.foundry_public
  identity {
    type = "SystemAssigned"
  }
}

# gpt-oss-120b needs a Foundry project in the resource before it can be deployed.
resource "azurerm_cognitive_account_project" "foundry" {
  count                = local.gateway ? 1 : 0
  name                 = "${local.short}-project"
  cognitive_account_id = azurerm_cognitive_account.foundry[0].id
  location             = var.foundry_location
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "open" {
  count                  = local.gateway && contains(local.s.models, "open") ? 1 : 0
  name                   = "gpt-oss-120b"
  cognitive_account_id   = azurerm_cognitive_account.foundry[0].id
  version_upgrade_option = "OnceCurrentVersionExpired"
  model {
    format  = "OpenAI-OSS"
    name    = "gpt-oss-120b"
    version = "1"
  }
  sku {
    name     = "GlobalStandard"
    capacity = var.capacity.open
  }
  # One deployment at a time per resource: Foundry refuses concurrent creates.
  depends_on = [azurerm_cognitive_account_project.foundry, azapi_resource.claude, azapi_resource.claude_small]
}
