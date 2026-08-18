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

variable "github_repository" {
  description = "GitHub repository allowed to request Azure OIDC tokens."
  type        = string
  default     = "tjsullivan1/sav"
}

variable "tf_state_resource_group_name" {
  description = "Resource group created by the one-time remote-state bootstrap."
  type        = string
}

variable "tf_state_storage_account_name" {
  description = "Storage account created by the one-time remote-state bootstrap."
  type        = string
}
