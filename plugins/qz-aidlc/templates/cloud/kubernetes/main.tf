# This project on a Kubernetes cluster: the app (with the model gateway beside it in the same pod, for an agent), its
# keys brought from the cloud's secret store by External Secrets Operator, a volume for its state, and a network
# policy. SIE, for the open models, is in sie.tf. What the project is (an HTTP service or a job, its port, its command)
# comes from starter.tf.

locals {
  s       = local.starter
  ns      = coalesce(var.namespace, local.s.slug)
  prefix  = coalesce(var.secret_prefix, local.s.slug)
  service = local.s.shape == "service"
  gateway = local.s.gateway
  sie     = var.sie_enabled == null ? local.s.gateway : var.sie_enabled
  labels  = { "app.kubernetes.io/name" = local.s.slug, "app.kubernetes.io/managed-by" = "opentofu" }

  agent_secret   = "${local.s.slug}-agent-keys"
  gateway_secret = "${local.s.slug}-gateway-keys"

  # The keys each container reads: its environment variable, and the key's name in the cloud's secret store. Provider
  # keys go to the gateway's container only; the agent holds the gateway's key and nothing else.
  agent_keys = local.gateway ? {
    AGENT_GATEWAY_KEY          = "${local.prefix}-gateway-key"
    OTEL_EXPORTER_OTLP_HEADERS = "${local.prefix}-otel-headers"
  } : {}
  gateway_keys = local.gateway ? merge({
    LITELLM_MASTER_KEY  = "${local.prefix}-gateway-key"
    ANTHROPIC_API_KEY   = "${local.prefix}-anthropic-api-key"
    LANGFUSE_PUBLIC_KEY = "${local.prefix}-langfuse-public-key"
    LANGFUSE_SECRET_KEY = "${local.prefix}-langfuse-secret-key"
  }, local.sie ? { SIE_AUTH_TOKEN = "${local.prefix}-sie-token" } : {}) : {}

  agent_env = local.gateway ? {
    AGENT_MODE                  = "live"
    APP_ENV                     = "production"
    AGENT_IDENTITY              = "oidc"
    AGENT_OIDC_ISSUER           = var.oidc_issuer
    AGENT_OIDC_AUDIENCE         = var.oidc_audience
    AGENT_OIDC_JWKS_URL         = var.oidc_jwks_url
    AGENT_GATEWAY               = "litellm"
    AGENT_GATEWAY_URL           = "http://127.0.0.1:4000"
    AGENT_STATE_DB              = "/data/state.db"
    AGENT_AUDIT_LOG             = "-"
    OTEL_EXPORTER_OTLP_ENDPOINT = "${var.langfuse_host}/api/public/otel"
    OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
  } : { APP_ENV = "production" }
  gateway_env = {
    LANGFUSE_HOST = var.langfuse_host
    SIE_API_BASE  = "http://sie-cluster-gateway.${var.sie_namespace}.svc.cluster.local:8080/v1"
  }
}

resource "kubernetes_namespace_v1" "app" {
  metadata {
    name = local.ns
    labels = merge(local.labels, {
      "pod-security.kubernetes.io/enforce" = "restricted"
    })
  }
}

resource "kubernetes_service_account_v1" "app" {
  metadata {
    name      = local.s.slug
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = local.labels
  }
  automount_service_account_token = false
}

# The keys, copied from the cloud's secret store into two Secrets by External Secrets Operator. Nothing here holds a
# value: a person puts each one in the store, and the operator brings it in (and again when it changes).
resource "kubernetes_manifest" "agent_keys" {
  count = local.gateway ? 1 : 0
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata   = { name = local.agent_secret, namespace = kubernetes_namespace_v1.app.metadata[0].name, labels = local.labels }
    spec = {
      refreshInterval = "1h"
      secretStoreRef  = { kind = "ClusterSecretStore", name = var.secret_store }
      target          = { name = local.agent_secret, creationPolicy = "Owner" }
      data            = [for env, key in local.agent_keys : { secretKey = env, remoteRef = { key = key } }]
    }
  }
}

resource "kubernetes_manifest" "gateway_keys" {
  count = local.gateway ? 1 : 0
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata   = { name = local.gateway_secret, namespace = kubernetes_namespace_v1.app.metadata[0].name, labels = local.labels }
    spec = {
      refreshInterval = "1h"
      secretStoreRef  = { kind = "ClusterSecretStore", name = var.secret_store }
      target          = { name = local.gateway_secret, creationPolicy = "Owner" }
      data            = [for env, key in local.gateway_keys : { secretKey = env, remoteRef = { key = key } }]
    }
  }
}

# The agent's state database (its runs, and each change its tools made, so a retried step is never made twice). SQLite
# wants one writer, so the app runs one replica and replaces it rather than running two side by side.
resource "kubernetes_persistent_volume_claim_v1" "state" {
  count = local.service ? 1 : 0
  metadata {
    name      = "${local.s.slug}-state"
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = local.labels
  }
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class
    resources {
      requests = { storage = var.state_size }
    }
  }
  wait_until_bound = false
}

resource "kubernetes_deployment_v1" "app" {
  # checkov:skip=CKV_K8S_14:The images come from var.agent_image and var.gateway_image, which refuse an image with no tag and latest; a static scan cannot see their values
  # checkov:skip=CKV_K8S_43:A release tag is accepted as well as a digest (variables.tf); a digest is the stronger pin
  # checkov:skip=CKV_K8S_22:Some starters write under HOME at run time; the README lists the writable root filesystem as a limit
  # checkov:skip=CKV_K8S_35:LiteLLM and the starters read their keys from the environment; the values come from the cloud's secret store through External Secrets
  count = local.service ? 1 : 0
  metadata {
    name      = local.s.slug
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = local.labels
  }
  spec {
    replicas = 1
    strategy {
      type = "Recreate"
    }
    selector {
      match_labels = local.labels
    }
    template {
      metadata {
        labels = local.labels
      }
      spec {
        service_account_name            = kubernetes_service_account_v1.app.metadata[0].name
        automount_service_account_token = false
        security_context {
          run_as_non_root = true
          run_as_user     = tostring(local.s.uid)
          fs_group        = tostring(local.s.uid)
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }
        dynamic "image_pull_secrets" {
          for_each = var.image_pull_secret == "" ? [] : [var.image_pull_secret]
          content {
            name = image_pull_secrets.value
          }
        }

        container {
          name              = "app"
          image             = var.agent_image
          image_pull_policy = "Always"
          args              = local.s.args
          port {
            name           = "http"
            container_port = local.s.port
          }
          dynamic "env" {
            for_each = local.agent_env
            content {
              name  = env.key
              value = env.value
            }
          }
          dynamic "env" {
            for_each = local.agent_keys
            content {
              name = env.key
              value_from {
                secret_key_ref {
                  name = local.agent_secret
                  key  = env.key
                }
              }
            }
          }
          readiness_probe {
            http_get {
              path = local.s.health
              port = local.s.port
            }
            period_seconds = 10
          }
          liveness_probe {
            http_get {
              path = local.s.health
              port = local.s.port
            }
            initial_delay_seconds = 15
            period_seconds        = 20
          }
          resources {
            requests = { cpu = var.resources.agent_cpu, memory = var.resources.agent_memory }
            limits   = { cpu = var.resources.agent_cpu, memory = var.resources.agent_memory }
          }
          security_context {
            allow_privilege_escalation = false
            privileged                 = false
            read_only_root_filesystem  = false
            run_as_non_root            = true
            capabilities {
              drop = ["ALL"]
            }
          }
          volume_mount {
            name       = "state"
            mount_path = "/data"
          }
        }

        dynamic "container" {
          for_each = local.gateway ? ["gateway"] : []
          content {
            name              = "gateway"
            image             = var.gateway_image
            image_pull_policy = "Always"
            port {
              name           = "gateway"
              container_port = 4000
            }
            dynamic "env" {
              for_each = local.gateway_env
              content {
                name  = env.key
                value = env.value
              }
            }
            dynamic "env" {
              for_each = local.gateway_keys
              content {
                name = env.key
                value_from {
                  secret_key_ref {
                    name = local.gateway_secret
                    key  = env.key
                  }
                }
              }
            }
            readiness_probe {
              http_get {
                path = "/health/liveliness"
                port = 4000
              }
              period_seconds = 10
            }
            liveness_probe {
              http_get {
                path = "/health/liveliness"
                port = 4000
              }
              initial_delay_seconds = 20
              period_seconds        = 20
            }
            resources {
              requests = { cpu = var.resources.gateway_cpu, memory = var.resources.gateway_memory }
              limits   = { cpu = var.resources.gateway_cpu, memory = var.resources.gateway_memory }
            }
            security_context {
              allow_privilege_escalation = false
              privileged                 = false
              read_only_root_filesystem  = false
              run_as_non_root            = true
              run_as_user                = "65534"
              capabilities {
                drop = ["ALL"]
              }
            }
          }
        }

        volume {
          name = "state"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.state[0].metadata[0].name
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = !local.gateway || (var.gateway_image != "" && var.oidc_issuer != "" && var.oidc_audience != "" && var.langfuse_host != "")
      error_message = "An agent needs gateway_image, oidc_issuer, oidc_audience and langfuse_host."
    }
  }
}

resource "kubernetes_service_v1" "app" {
  count = local.service ? 1 : 0
  metadata {
    name      = local.s.slug
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = local.labels
  }
  spec {
    type     = "ClusterIP"
    selector = local.labels
    port {
      name        = "http"
      port        = local.service ? local.s.port : 80 # (a job has no port, and no Service)
      target_port = local.service ? local.s.port : 80
    }
  }
}

# A project that runs to completion: a CronJob that starts suspended, so a run happens only when someone starts one
# (or turns the schedule on). It runs the image's own command.
resource "kubernetes_cron_job_v1" "app" {
  count = local.service ? 0 : 1
  metadata {
    name      = local.s.slug
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = local.labels
  }
  spec {
    schedule                      = var.job_schedule
    suspend                       = var.job_suspended
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 3
    failed_jobs_history_limit     = 3
    job_template {
      metadata {
        labels = local.labels
      }
      spec {
        backoff_limit = 1
        template {
          metadata {
            labels = local.labels
          }
          spec {
            service_account_name            = kubernetes_service_account_v1.app.metadata[0].name
            automount_service_account_token = false
            restart_policy                  = "Never"
            security_context {
              run_as_non_root = true
              run_as_user     = tostring(local.s.uid)
              seccomp_profile {
                type = "RuntimeDefault"
              }
            }
            dynamic "image_pull_secrets" {
              for_each = var.image_pull_secret == "" ? [] : [var.image_pull_secret]
              content {
                name = image_pull_secrets.value
              }
            }
            container {
              name              = "app"
              image             = var.agent_image
              image_pull_policy = "Always"
              resources {
                requests = { cpu = var.resources.agent_cpu, memory = var.resources.agent_memory }
                limits   = { cpu = var.resources.agent_cpu, memory = var.resources.agent_memory }
              }
              security_context {
                allow_privilege_escalation = false
                privileged                 = false
                read_only_root_filesystem  = false
                run_as_non_root            = true
                capabilities {
                  drop = ["ALL"]
                }
              }
            }
          }
        }
      }
    }
  }
}

# Who may reach the app, and what it may reach: its own namespace and the ingress namespaces in; DNS, SIE and HTTPS
# out (the Claude API, the identity provider, Langfuse).
resource "kubernetes_network_policy_v1" "app" {
  metadata {
    name      = local.s.slug
    namespace = kubernetes_namespace_v1.app.metadata[0].name
    labels    = local.labels
  }
  spec {
    pod_selector {
      match_labels = local.labels
    }
    policy_types = ["Ingress", "Egress"]
    # A job listens on nothing, so nothing may reach it.
    dynamic "ingress" {
      for_each = local.service ? [local.s.port] : []
      content {
        from {
          pod_selector {}
        }
        dynamic "from" {
          for_each = var.ingress_namespaces
          content {
            namespace_selector {
              match_labels = { "kubernetes.io/metadata.name" = from.value }
            }
          }
        }
        ports {
          port     = tostring(ingress.value)
          protocol = "TCP"
        }
      }
    }
    egress {
      ports {
        port     = "53"
        protocol = "UDP"
      }
      ports {
        port     = "53"
        protocol = "TCP"
      }
    }
    egress {
      to {
        namespace_selector {
          match_labels = { "kubernetes.io/metadata.name" = var.sie_namespace }
        }
      }
      ports {
        port     = "8080"
        protocol = "TCP"
      }
    }
    egress {
      ports {
        port     = "443"
        protocol = "TCP"
      }
    }
  }
}
