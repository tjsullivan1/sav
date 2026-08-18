# Terraform State and GitHub OIDC Bootstrap

Terraform owns Azure resources and the dedicated Microsoft Entra application used by GitHub Actions
after this one-time bootstrap. Do not create a client secret, save an Azure credential JSON document,
or add an Azure credential to GitHub Secrets.

## Prerequisites

Run these steps as the person who will perform the initial apply. That identity needs:

- **Contributor** on the target subscription to create the state resource group and storage account.
- **Storage Blob Data Contributor** on the state storage account to use the Azure AD-backed Terraform
  backend.
- A directory role or delegated Microsoft Graph permission that permits application registration
  management (for example, Application Administrator or Cloud Application Administrator).
- **User Access Administrator** or **Owner** on the production resource group and state storage
  account scope, so Terraform can grant the GitHub service principal its required Azure roles.

The tenant administrator must consent to the permissions required by the AzureAD Terraform provider
when the initial operator cannot grant that consent. Keep those permissions in the initial operator
identity; they are not GitHub secrets and are not granted to the GitHub workload identity.

## Create protected remote state

Choose a globally unique, lowercase storage account name. The commands below use Azure AD
authorization rather than a storage key. Replace the values before running them in PowerShell.

```powershell
$subscriptionId = "<subscription-id>"
$location = "canadacentral"
$stateResourceGroup = "rg-blog-to-podcast-tfstate"
$stateStorageAccount = "<globally-unique-storage-account>"
$stateContainer = "tfstate"

az login
az account set --subscription $subscriptionId
az group create --name $stateResourceGroup --location $location
az storage account create `
  --name $stateStorageAccount `
  --resource-group $stateResourceGroup `
  --location $location `
  --sku Standard_RAGRS `
  --kind StorageV2 `
  --min-tls-version TLS1_2 `
  --allow-blob-public-access false
az storage account blob-service-properties update `
  --account-name $stateStorageAccount `
  --resource-group $stateResourceGroup `
  --enable-versioning true `
  --enable-delete-retention true `
  --delete-retention-days 30
az role assignment create `
  --assignee (az ad signed-in-user show --query id --output tsv) `
  --role "Storage Blob Data Contributor" `
  --scope (az storage account show --name $stateStorageAccount --resource-group $stateResourceGroup --query id --output tsv)
az storage container create `
  --name $stateContainer `
  --account-name $stateStorageAccount `
  --auth-mode login
```

Versioning and 30-day blob soft-delete protect state recovery. The state account is deliberately
outside the Terraform-managed production resource group: Terraform must never be able to destroy
the backend that records its own resources.

## Initial local Terraform apply

From the repository root, authenticate through Azure CLI and initialize Terraform with the protected
backend. Substitute the names selected above.

```powershell
az login --tenant "<tenant-id>"
az account set --subscription "<subscription-id>"
Set-Location infra
terraform init -input=false `
  -backend-config="resource_group_name=rg-blog-to-podcast-tfstate" `
  -backend-config="storage_account_name=<globally-unique-storage-account>" `
  -backend-config="container_name=tfstate" `
  -backend-config="key=production.tfstate" `
  -backend-config="use_azuread_auth=true"
terraform apply -input=false `
  -var="tf_state_resource_group_name=rg-blog-to-podcast-tfstate" `
  -var="tf_state_storage_account_name=<globally-unique-storage-account>"
```

The apply creates the production resource group, separate plan and deployment Entra applications
and service principals, GitHub federated credentials, and Azure role assignments. The pull-request
identity has Reader on the production resource group and Storage Blob Data Reader on the state
account, so it cannot change Azure. The reserved main-branch deployment identity has Contributor on
the production resource group and Storage Blob Data Contributor on the state account.

## Configure GitHub Actions

Copy the three Terraform outputs and state identifiers into **Settings > Secrets and variables >
Actions > Variables**. These are identifiers, not secrets:

| Variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | `terraform output -raw github_actions_plan_client_id` |
| `AZURE_TENANT_ID` | `terraform output -raw github_actions_tenant_id` |
| `AZURE_SUBSCRIPTION_ID` | `terraform output -raw github_actions_subscription_id` |
| `TF_STATE_RESOURCE_GROUP` | State resource group name |
| `TF_STATE_STORAGE_ACCOUNT` | State storage account name |
| `TF_STATE_CONTAINER` | `tfstate` |

Open a pull request after setting the variables. The workflow requests a short-lived GitHub OIDC
token, produces a non-locking read-only Terraform plan, and has no `terraform apply` step. It never
accepts a stored Azure credential.
