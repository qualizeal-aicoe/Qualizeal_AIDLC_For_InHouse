output "keys_to_set" {
  description = "The Key Vault secrets a person creates before setting start_app = true. Nothing here holds a value."
  value       = sort([for k in local.key_names : "${local.name}-${k}"])
}

output "key_vault" {
  description = "The app's Key Vault."
  value       = azurerm_key_vault.app.name
}

output "foundry_endpoint" {
  description = "Foundry's Claude endpoint, which the gateway calls (empty for a project without the gateway)."
  value       = local.gateway ? local.gateway_env.AZURE_AI_API_BASE : ""
}

output "app_fqdn" {
  description = "The app's address (empty for a job, or before start_app)."
  value       = length(azurerm_container_app.app) > 0 ? azurerm_container_app.app[0].ingress[0].fqdn : ""
}
