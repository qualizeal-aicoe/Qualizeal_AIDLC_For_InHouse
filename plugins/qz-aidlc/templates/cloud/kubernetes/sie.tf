# SIE (Superlinked Inference Engine, Apache 2.0): the open models in the client's own cluster, behind one
# OpenAI-compatible API. The gateway falls back to its agent model when Claude fails or spends its budget. Its
# telemetry is off and both its tokens are on (sie-values.yaml); its gateway token comes from the cloud's secret store.
# GPU nodes are the cluster's: SIE's Terraform modules create them on EKS, AKS, GKE and ACK
# (github.com/superlinked/terraform-aws-sie, terraform-azure-sie, terraform-google-sie, terraform-alicloud-sie).

resource "kubernetes_namespace_v1" "sie" {
  count = local.sie ? 1 : 0
  metadata {
    name   = var.sie_namespace
    labels = { "app.kubernetes.io/managed-by" = "opentofu" }
  }
}

resource "kubernetes_manifest" "sie_token" {
  count = local.sie ? 1 : 0
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata   = { name = "sie-gateway-token", namespace = kubernetes_namespace_v1.sie[0].metadata[0].name }
    spec = {
      refreshInterval = "1h"
      secretStoreRef  = { kind = "ClusterSecretStore", name = var.secret_store }
      target          = { name = "sie-gateway-token", creationPolicy = "Owner" }
      data            = [{ secretKey = "SIE_AUTH_TOKEN", remoteRef = { key = "${local.prefix}-sie-token" } }]
    }
  }
}

resource "helm_release" "sie" {
  count      = local.sie ? 1 : 0
  name       = "sie-cluster" # the release name makes SIE's gateway sie-cluster-gateway.<namespace>.svc
  namespace  = kubernetes_namespace_v1.sie[0].metadata[0].name
  repository = "oci://ghcr.io/superlinked/charts"
  chart      = "sie-cluster"
  version    = "0.11.1"
  values     = concat([file("${path.module}/sie-values.yaml")], var.sie_extra_values)
  wait       = false # GPU nodes can take a while to arrive; the pods start when they do
  timeout    = 900

  depends_on = [kubernetes_manifest.sie_token]
}
