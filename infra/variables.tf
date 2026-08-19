variable "location" {
  description = "Azure region for the production foundation."
  type        = string
  default     = "Canada Central"
}

variable "resource_group_name" {
  description = "Name of the Terraform-managed production resource group."
  type        = string
  default     = "rg-blog-to-podcast-prod"
}

variable "github_oidc_subject_prefix" {
  description = "GitHub Actions OIDC subject prefix emitted for this repository."
  type        = string
  default     = "repo:tjsullivan1@191369/sav@1334625838"
}

variable "tf_state_resource_group_name" {
  description = "Resource group created by the one-time remote-state bootstrap."
  type        = string
}

variable "tf_state_storage_account_name" {
  description = "Storage account created by the one-time remote-state bootstrap."
  type        = string
}

variable "application_display_name" {
  description = "Display-name prefix for the production Entra applications."
  type        = string
  default     = "Blog to Podcast"
}

variable "application_image_name" {
  description = "Repository name for the immutable production container image."
  type        = string
  default     = "blog-to-podcast"
}

variable "application_image_tag" {
  description = "Immutable image tag deployed to each Container App."
  type        = string
  default     = "latest"
}

variable "api_application_id_uri" {
  description = "Globally unique URI used as the Entra API application identifier."
  type        = string
  default     = "blog-to-podcast-prod-api"
}

variable "owner_object_id" {
  description = "Microsoft Entra object ID allowed to access the public UI and Episode API."
  type        = string
  nullable    = false
}

variable "storage_account_name" {
  description = "Globally unique lowercase name for the production Azure Storage account."
  type        = string
  default     = "stblogtopodcastprod"
}

variable "key_vault_name" {
  description = "Globally unique name for the production Key Vault."
  type        = string
  default     = "kv-blog-to-podcast-prod"
}

variable "container_app_environment_name" {
  description = "Name for the production Container Apps environment."
  type        = string
  default     = "cae-blog-to-podcast-prod"
}

variable "container_registry_name" {
  description = "Globally unique lowercase name for the production Azure Container Registry."
  type        = string
  default     = "acrblogtopodcastprod"
}

variable "log_analytics_workspace_name" {
  description = "Name for the production Log Analytics workspace."
  type        = string
  default     = "log-blog-to-podcast-prod"
}

variable "application_insights_name" {
  description = "Name for the production Application Insights resource."
  type        = string
  default     = "appi-blog-to-podcast-prod"
}

variable "openai_account_name" {
  description = "Globally unique name for the dedicated Azure OpenAI account."
  type        = string
  default     = "oai-blog-to-podcast-prod"
}

variable "openai_deployment_name" {
  description = "Name for the Azure OpenAI model deployment."
  type        = string
  default     = "chat"
}

variable "openai_model_name" {
  description = "Azure OpenAI model name deployed for Script generation."
  type        = string
  default     = "gpt-4o-mini"
}

variable "openai_model_version" {
  description = "Azure OpenAI model version deployed for Script generation."
  type        = string
  default     = "2024-07-18"
}
