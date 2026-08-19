mock_provider "azurerm" {}

mock_provider "azuread" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    tenant_id       = "22222222-2222-2222-2222-222222222222"
    subscription_id = "33333333-3333-3333-3333-333333333333"
  }
}

override_data {
  target = data.azurerm_storage_account.terraform_state
  values = {
    id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-blog-to-podcast-tfstate/providers/Microsoft.Storage/storageAccounts/stblogtopodcaststate"
  }
}

run "provisions_a_single_private_worker_platform" {
  command = plan

  variables {
    tf_state_resource_group_name   = "rg-blog-to-podcast-tfstate"
    tf_state_storage_account_name  = "stblogtopodcaststate"
    storage_account_name           = "stblogtopodcastprod"
    key_vault_name                 = "kv-blog-to-podcast-prod"
    container_app_environment_name = "cae-blog-to-podcast-prod"
    container_registry_name        = "acrblogtopodcastprod"
    log_analytics_workspace_name   = "log-blog-to-podcast-prod"
    application_insights_name      = "appi-blog-to-podcast-prod"
    openai_account_name            = "oai-blog-to-podcast-prod"
    owner_object_id                = "11111111-1111-1111-1111-111111111111"
  }

  assert {
    condition     = azurerm_resource_group.production.location == "Canada Central"
    error_message = "The production stack must default to Canada Central."
  }

  assert {
    condition     = azurerm_container_app.worker.template[0].max_replicas == 1
    error_message = "The worker must be limited to one replica."
  }

  assert {
    condition = alltrue([
      azurerm_container_app.worker.template[0].custom_scale_rule[0].custom_rule_type == "azure-queue",
      azurerm_container_app.worker.template[0].custom_scale_rule[0].metadata.queueLength == "1",
    ])
    error_message = "The worker must scale from the Generation Jobs queue using its managed identity."
  }

  assert {
    condition     = length(azurerm_container_app.worker.ingress) == 0
    error_message = "The worker must not have public ingress."
  }

  assert {
    condition = alltrue([
      azurerm_role_assignment.worker_openai_user.role_definition_name == "Cognitive Services OpenAI User",
      azurerm_role_assignment.worker_key_vault_secrets_user.role_definition_name == "Key Vault Secrets User",
      azurerm_role_assignment.worker_storage_blob_contributor.role_definition_name == "Storage Blob Data Contributor",
      azurerm_role_assignment.worker_storage_queue_contributor.role_definition_name == "Storage Queue Data Contributor",
      azurerm_role_assignment.worker_storage_table_contributor.role_definition_name == "Storage Table Data Contributor",
    ])
    error_message = "The worker must use only its required data-plane roles."
  }

  assert {
    condition = alltrue([
      azurerm_storage_management_policy.production.rule[0].actions[0].base_blob[0].delete_after_days_since_modification_greater_than == 30,
      azurerm_storage_management_policy.production.rule[1].actions[0].base_blob[0].delete_after_days_since_modification_greater_than == 30,
    ])
    error_message = "Temporary and failed Job blobs must expire after 30 days."
  }

  assert {
    condition = alltrue([
      length(azurerm_container_app.ui.secret) == 0,
      length(azurerm_container_app.api.secret) == 0,
    ])
    error_message = "Provider secrets must not be configured for the UI or API."
  }

  assert {
    condition     = azuread_app_role_assignment.owner_api_access[0].app_role_id != null
    error_message = "The configured owner must receive the API app role."
  }
}
