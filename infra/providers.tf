provider "azurerm" {
  features {}
}

provider "azuread" {}

provider "azapi" {}

data "azurerm_client_config" "current" {}
