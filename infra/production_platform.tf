locals {
  application_image       = "${azurerm_container_registry.production.login_server}/${var.application_image_name}:${var.application_image_tag}"
  episode_api_app_role_id = one([for role in azuread_application.episode_api.app_role : role.id])
  key_vault_uri           = "https://${azurerm_key_vault.production.name}.vault.azure.net"
}

resource "azurerm_log_analytics_workspace" "production" {
  name                = var.log_analytics_workspace_name
  location            = azurerm_resource_group.production.location
  resource_group_name = azurerm_resource_group.production.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_application_insights" "production" {
  name                = var.application_insights_name
  location            = azurerm_resource_group.production.location
  resource_group_name = azurerm_resource_group.production.name
  workspace_id        = azurerm_log_analytics_workspace.production.id
  application_type    = "web"
}

resource "azurerm_container_app_environment" "production" {
  name                       = var.container_app_environment_name
  location                   = azurerm_resource_group.production.location
  resource_group_name        = azurerm_resource_group.production.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.production.id
}

resource "azurerm_container_registry" "production" {
  name                = var.container_registry_name
  location            = azurerm_resource_group.production.location
  resource_group_name = azurerm_resource_group.production.name
  sku                 = "Standard"
  admin_enabled       = false
}

resource "azurerm_user_assigned_identity" "ui" {
  name                = "${var.container_app_environment_name}-ui"
  location            = azurerm_resource_group.production.location
  resource_group_name = azurerm_resource_group.production.name
}

resource "azurerm_user_assigned_identity" "api" {
  name                = "${var.container_app_environment_name}-api"
  location            = azurerm_resource_group.production.location
  resource_group_name = azurerm_resource_group.production.name
}

resource "azurerm_user_assigned_identity" "worker" {
  name                = "${var.container_app_environment_name}-worker"
  location            = azurerm_resource_group.production.location
  resource_group_name = azurerm_resource_group.production.name
}

resource "azurerm_key_vault" "production" {
  name                       = var.key_vault_name
  location                   = azurerm_resource_group.production.location
  resource_group_name        = azurerm_resource_group.production.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 30
}

resource "azurerm_storage_account" "production" {
  name                            = var.storage_account_name
  resource_group_name             = azurerm_resource_group.production.name
  location                        = azurerm_resource_group.production.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
}

resource "azurerm_storage_container" "episodes" {
  name                  = "episodes"
  storage_account_id    = azurerm_storage_account.production.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "scripts" {
  name                  = "scripts"
  storage_account_id    = azurerm_storage_account.production.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "temporary" {
  name                  = "temporary"
  storage_account_id    = azurerm_storage_account.production.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "job_data" {
  name                  = "job-data"
  storage_account_id    = azurerm_storage_account.production.id
  container_access_type = "private"
}

resource "azurerm_storage_queue" "generation_jobs" {
  name               = "generation-jobs"
  storage_account_id = azurerm_storage_account.production.id
}

resource "azurerm_storage_table" "generation_jobs" {
  name               = "GenerationJobs"
  storage_account_id = azurerm_storage_account.production.id
}

resource "azurerm_storage_table" "episodes" {
  name               = "Episodes"
  storage_account_id = azurerm_storage_account.production.id
}

resource "azurerm_storage_management_policy" "production" {
  storage_account_id = azurerm_storage_account.production.id

  rule {
    name    = "expire-temporary-source-material"
    enabled = true

    filters {
      prefix_match = ["temporary/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 30
      }
    }
  }

  rule {
    name    = "expire-terminal-job-data"
    enabled = true

    filters {
      prefix_match = ["job-data/failed/", "job-data/cancelled/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 30
      }
    }
  }
}

resource "azurerm_cognitive_account" "openai" {
  name                  = var.openai_account_name
  location              = azurerm_resource_group.production.location
  resource_group_name   = azurerm_resource_group.production.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = var.openai_account_name
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.openai_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_model_name
    version = var.openai_model_version
  }

  sku {
    name     = "Standard"
    capacity = 1
  }
}

resource "azuread_application" "episode_api" {
  display_name     = "${var.application_display_name} API"
  identifier_uris  = ["api://${var.api_application_id_uri}"]
  sign_in_audience = "AzureADMyOrg"

  app_role {
    allowed_member_types = ["Application", "User"]
    description          = "Submit and retrieve Episodes through the API."
    display_name         = "Episode API access"
    enabled              = true
    id                   = uuidv5("dns", "${var.api_application_id_uri}/episodes.access")
    value                = "Episodes.Access"
  }
}

resource "azuread_service_principal" "episode_api" {
  client_id                    = azuread_application.episode_api.client_id
  app_role_assignment_required = true
}

resource "azuread_application" "episode_ui" {
  display_name     = "${var.application_display_name} UI"
  sign_in_audience = "AzureADMyOrg"

  required_resource_access {
    resource_app_id = azuread_application.episode_api.client_id

    resource_access {
      id   = local.episode_api_app_role_id
      type = "Role"
    }
  }
}

resource "azuread_service_principal" "episode_ui" {
  client_id = azuread_application.episode_ui.client_id
}

resource "azurerm_container_app" "ui" {
  name                         = "${var.container_app_environment_name}-ui"
  container_app_environment_id = azurerm_container_app_environment.production.id
  resource_group_name          = azurerm_resource_group.production.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ui.id]
  }

  registry {
    server   = azurerm_container_registry.production.login_server
    identity = azurerm_user_assigned_identity.ui.id
  }

  ingress {
    external_enabled = true
    target_port      = 8501

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    container {
      name   = "ui"
      image  = local.application_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.production.connection_string
      }

    }

    min_replicas = 1
    max_replicas = 1
  }
}

resource "azurerm_container_app" "api" {
  name                         = "${var.container_app_environment_name}-api"
  container_app_environment_id = azurerm_container_app_environment.production.id
  resource_group_name          = azurerm_resource_group.production.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  registry {
    server   = azurerm_container_registry.production.login_server
    identity = azurerm_user_assigned_identity.api.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    container {
      name   = "api"
      image  = local.application_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.production.connection_string
      }

      env {
        name  = "AZURE_STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.production.name
      }

      env {
        name  = "ENTRA_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }

      env {
        name  = "API_APPLICATION_ID_URI"
        value = var.api_application_id_uri
      }

      env {
        name  = "APPROVED_USER_SUBJECTS"
        value = coalesce(var.owner_object_id, "")
      }

      command = ["uvicorn"]
      args = [
        "blog_to_podcast.runtime:create_api_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
      ]
    }

    min_replicas = 1
    max_replicas = 1
  }
}

resource "azurerm_container_app" "worker" {
  name                         = "${var.container_app_environment_name}-worker"
  container_app_environment_id = azurerm_container_app_environment.production.id
  resource_group_name          = azurerm_resource_group.production.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.worker.id]
  }

  registry {
    server   = azurerm_container_registry.production.login_server
    identity = azurerm_user_assigned_identity.worker.id
  }

  secret {
    name                = "firecrawl-api-key"
    key_vault_secret_id = "${local.key_vault_uri}/secrets/firecrawl-api-key"
    identity            = azurerm_user_assigned_identity.worker.id
  }

  secret {
    name                = "elevenlabs-api-key"
    key_vault_secret_id = "${local.key_vault_uri}/secrets/elevenlabs-api-key"
    identity            = azurerm_user_assigned_identity.worker.id
  }

  secret {
    name                = "azure-openai-api-key"
    key_vault_secret_id = "${local.key_vault_uri}/secrets/azure-openai-api-key"
    identity            = azurerm_user_assigned_identity.worker.id
  }

  template {
    container {
      name   = "worker"
      image  = local.application_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "FIRECRAWL_API_KEY"
        secret_name = "firecrawl-api-key"
      }

      env {
        name        = "ELEVENLABS_API_KEY"
        secret_name = "elevenlabs-api-key"
      }

      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }

      env {
        name  = "AZURE_OPENAI_BASE_URL"
        value = "${azurerm_cognitive_account.openai.endpoint}openai/v1/"
      }

      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = azurerm_cognitive_deployment.chat.name
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.production.connection_string
      }

      env {
        name  = "AZURE_STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.production.name
      }

      command = ["python"]
      args    = ["-m", "blog_to_podcast.worker"]
    }

    min_replicas = 0
    max_replicas = 1

    custom_scale_rule {
      name             = "generation-jobs"
      custom_rule_type = "azure-queue"
      identity_id      = azurerm_user_assigned_identity.worker.id
      metadata = {
        accountName = azurerm_storage_account.production.name
        queueName   = azurerm_storage_queue.generation_jobs.name
        queueLength = "1"
      }
    }
  }
}

resource "azuread_app_role_assignment" "ui_api_access" {
  app_role_id         = local.episode_api_app_role_id
  principal_object_id = azurerm_user_assigned_identity.ui.principal_id
  resource_object_id  = azuread_service_principal.episode_api.object_id
}

resource "azuread_app_role_assignment" "owner_api_access" {
  count = var.owner_object_id == null ? 0 : 1

  app_role_id         = local.episode_api_app_role_id
  principal_object_id = var.owner_object_id
  resource_object_id  = azuread_service_principal.episode_api.object_id
}

resource "azurerm_role_assignment" "ui_acr_pull" {
  scope                = azurerm_container_registry.production.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.ui.principal_id
}

resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = azurerm_container_registry.production.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "worker_acr_pull" {
  scope                = azurerm_container_registry.production.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_key_vault_secrets_user" {
  scope                = azurerm_key_vault.production.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_storage_blob_contributor" {
  scope                = azurerm_storage_account.production.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_storage_queue_contributor" {
  scope                = azurerm_storage_account.production.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "worker_storage_table_contributor" {
  scope                = azurerm_storage_account.production.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_user_assigned_identity.worker.principal_id
}

resource "azurerm_role_assignment" "api_storage_blob_reader" {
  scope                = azurerm_storage_account.production.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "api_storage_queue_contributor" {
  scope                = azurerm_storage_account.production.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "api_storage_table_contributor" {
  scope                = azurerm_storage_account.production.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}
