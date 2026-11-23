# OpenTofu (or Terraform) for this project on a Kubernetes cluster the client runs. `qz cloud add kubernetes` wrote it.
# Exact provider versions: change them on purpose, after reading their release notes, and run the tests again.
terraform {
  required_version = ">= 1.8"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "3.5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "3.3.0"
    }
  }
}

# The cluster comes from a kubeconfig the person who applies holds; nothing about it is stored here.
provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kube_context
}

provider "helm" {
  kubernetes = {
    config_path    = var.kubeconfig_path
    config_context = var.kube_context
  }
}
