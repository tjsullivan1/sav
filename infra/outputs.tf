output "github_actions_plan_client_id" {
  description = "Application (client) ID for the AZURE_CLIENT_ID GitHub Actions variable."
  value       = azuread_application.github_actions_plan.client_id
}

output "github_actions_plan_service_principal_object_id" {
  description = "Object ID granted read-only Azure and Microsoft Entra permissions for plans."
  value       = azuread_service_principal.github_actions_plan.object_id
}

output "github_actions_deploy_client_id" {
  description = "Client ID reserved for the later main-branch deployment workflow."
  value       = azuread_application.github_actions_deploy.client_id
}

output "github_actions_tenant_id" {
  description = "Tenant ID for the AZURE_TENANT_ID GitHub Actions variable."
  value       = data.azurerm_client_config.current.tenant_id
}

output "github_actions_subscription_id" {
  description = "Subscription ID for the AZURE_SUBSCRIPTION_ID GitHub Actions variable."
  value       = data.azurerm_client_config.current.subscription_id
}
