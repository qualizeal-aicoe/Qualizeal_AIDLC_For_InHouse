# OpenTofu (or Terraform) for this project on Google Cloud. `qz cloud add gcp` wrote it.
# Exact provider versions: change them on purpose, after reading their release notes, and run the tests again.
terraform {
  required_version = ">= 1.8"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.12.0"
    }
  }
}

# Credentials come from the person or pipeline that applies (their own identity or workload identity, never a key file).
provider "google" {
  project = var.project_id
  region  = var.region
}
