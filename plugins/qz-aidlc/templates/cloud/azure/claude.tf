# Claude in Foundry. The deployments go through the azapi provider because azurerm's deployment resource does not take
# modelProviderData yet: the organization, country and industry Anthropic's terms through the Azure Marketplace ask for.
# Applying these accepts those terms for the client, so the three values have no default here and the client's
# administrator sets them. Microsoft's own Terraform sample for Claude in Foundry deploys the same way
# (github.com/Azure-Samples/claude). Deployed one after the other: Foundry refuses concurrent creates on one resource.

locals {
  claude_terms = {
    organizationName = var.claude_organization_name
    countryCode      = var.claude_country_code
    industry         = var.claude_industry
  }
}

resource "azapi_resource" "claude" {
  count                     = local.gateway && contains(local.s.models, "claude") ? 1 : 0
  type                      = "Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview"
  name                      = "claude-sonnet-5-5"
  parent_id                 = azurerm_cognitive_account.foundry[0].id
  schema_validation_enabled = false # modelProviderData is not in the published schema yet
  body = {
    sku = { name = "GlobalStandard", capacity = var.capacity.claude }
    properties = {
      model                = { format = "Anthropic", name = "claude-sonnet-5-5", version = var.claude_model_version }
      modelProviderData    = local.claude_terms
      versionUpgradeOption = "OnceCurrentVersionExpired" # pinned: a new version is a decision, after the gold set
      raiPolicyName        = "Microsoft.DefaultV2"
    }
  }
  depends_on = [azurerm_cognitive_account_project.foundry]

  lifecycle {
    precondition {
      condition     = var.claude_organization_name != "" && length(var.claude_country_code) == 2 && contains(["technology", "finance", "healthcare", "education", "retail", "manufacturing", "government", "media", "other"], var.claude_industry)
      error_message = "Set claude_organization_name, claude_country_code and claude_industry: applying the Claude deployments accepts Anthropic's terms for the client."
    }
  }
}

resource "azapi_resource" "claude_small" {
  count                     = local.gateway && contains(local.s.models, "claude-small") ? 1 : 0
  type                      = "Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview"
  name                      = "claude-haiku-5-5"
  parent_id                 = azurerm_cognitive_account.foundry[0].id
  schema_validation_enabled = false
  body = {
    sku = { name = "GlobalStandard", capacity = var.capacity.claude_small }
    properties = {
      model                = { format = "Anthropic", name = "claude-haiku-5-5", version = var.claude_model_version }
      modelProviderData    = local.claude_terms
      versionUpgradeOption = "OnceCurrentVersionExpired"
      raiPolicyName        = "Microsoft.DefaultV2"
    }
  }
  depends_on = [azurerm_cognitive_account_project.foundry, azapi_resource.claude]

  lifecycle {
    precondition {
      condition     = var.claude_organization_name != "" && length(var.claude_country_code) == 2 && contains(["technology", "finance", "healthcare", "education", "retail", "manufacturing", "government", "media", "other"], var.claude_industry)
      error_message = "Set claude_organization_name, claude_country_code and claude_industry: applying the Claude deployments accepts Anthropic's terms for the client."
    }
  }
}
