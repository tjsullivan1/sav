resource "azurerm_resource_group" "production" {
  name     = var.resource_group_name
  location = var.location
}

resource "azuread_application" "github_actions_plan" {
  display_name = "blog-to-podcast-github-actions-plan"
}

resource "azuread_service_principal" "github_actions_plan" {
  client_id = azuread_application.github_actions_plan.client_id
}

resource "azuread_application_federated_identity_credential" "github_actions_plan_pull_request" {
  application_id = azuread_application.github_actions_plan.id
  display_name   = "github-pull-requests"
  description    = "Allows read-only Terraform plans from pull requests."
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:pull_request"
}

resource "azuread_application" "github_actions_deploy" {
  display_name = "blog-to-podcast-github-actions-deploy"
}

resource "azuread_service_principal" "github_actions_deploy" {
  client_id = azuread_application.github_actions_deploy.client_id
}

resource "azuread_application_federated_identity_credential" "github_actions_deploy_main" {
  application_id = azuread_application.github_actions_deploy.id
  display_name   = "github-main"
  description    = "Reserves main-branch federation for a later deployment workflow."
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "github_actions_plan_production_reader" {
  scope                = azurerm_resource_group.production.id
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.github_actions_plan.object_id
}

data "azurerm_storage_account" "terraform_state" {
  name                = var.tf_state_storage_account_name
  resource_group_name = var.tf_state_resource_group_name
}

resource "azurerm_role_assignment" "github_actions_plan_state_blob_reader" {
  scope                = data.azurerm_storage_account.terraform_state.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azuread_service_principal.github_actions_plan.object_id
}

resource "azurerm_role_assignment" "github_actions_deploy_production_contributor" {
  scope                = azurerm_resource_group.production.id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.github_actions_deploy.object_id
}

resource "azurerm_role_assignment" "github_actions_deploy_state_blob_contributor" {
  scope                = data.azurerm_storage_account.terraform_state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.github_actions_deploy.object_id
}
