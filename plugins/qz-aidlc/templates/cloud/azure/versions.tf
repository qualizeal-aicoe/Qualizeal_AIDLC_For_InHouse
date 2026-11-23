# OpenTofu (or Terraform) for this project on Microsoft Azure. `qz cloud add azure` wrote it.
# Exact provider versions: change them on purpose, after reading their release notes, and run the tests again.
terraform {
  required_version = ">= 1.8"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.14.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "2.14.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
}

# Credentials come from the person or pipeline that applies (az login, or a workload identity), never a file here.
provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

provider "azapi" {
  subscription_id = var.subscription_id
}
