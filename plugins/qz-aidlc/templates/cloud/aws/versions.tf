# OpenTofu (or Terraform) for this project on AWS. `qz cloud add aws` wrote it.
# Exact provider versions: change them on purpose, after reading their release notes, and run the tests again.
terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.73.0"
    }
  }
}

# Credentials come from the person or pipeline that applies (a role, never keys in a file).
provider "aws" {
  region = var.region
  default_tags {
    tags = { "app" = local.starter.slug, "managed-by" = "opentofu" }
  }
}
