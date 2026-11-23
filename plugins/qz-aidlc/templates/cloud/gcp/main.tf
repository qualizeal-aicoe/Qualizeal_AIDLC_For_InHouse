# This project on Cloud Run: one service holding the app and, for an agent, the model gateway beside it as a sidecar
# (the two talk over localhost), its keys named in Secret Manager, its own service account. The gateway reaches Claude
# and the open-weight model on Gemini Enterprise Agent Platform with that account: no model key exists. What the
# project is (an HTTP service or a job) comes from starter.tf.

locals {
  s       = local.starter
  service = local.s.shape == "service"
  gateway = local.s.gateway
  name    = local.s.slug
  sa_id   = trimsuffix(substr("${local.name}-app", 0, 30), "-")

  # Each key this app reads: its environment variable, and its secret in Secret Manager. A person adds the values as
  # versions; nothing here holds one. Provider keys: none on Google Cloud, the gateway calls Claude with the account.
  agent_keys   = local.gateway ? { AGENT_GATEWAY_KEY = "gateway-key", OTEL_EXPORTER_OTLP_HEADERS = "otel-headers" } : {}
  gateway_keys = local.gateway ? { LITELLM_MASTER_KEY = "gateway-key", LANGFUSE_PUBLIC_KEY = "langfuse-public-key", LANGFUSE_SECRET_KEY = "langfuse-secret-key" } : {}
  key_names    = toset(concat(values(local.agent_keys), values(local.gateway_keys)))

  agent_env = local.gateway ? {
    AGENT_MODE                  = "live"
    APP_ENV                     = "production"
    AGENT_IDENTITY              = "oidc"
    AGENT_OIDC_ISSUER           = var.oidc_issuer
    AGENT_OIDC_AUDIENCE         = var.oidc_audience
    AGENT_OIDC_JWKS_URL         = var.oidc_jwks_url
    AGENT_GATEWAY               = "litellm"
    AGENT_GATEWAY_URL           = "http://127.0.0.1:4000"
    AGENT_AUDIT_LOG             = "-"
    OTEL_EXPORTER_OTLP_ENDPOINT = "${var.langfuse_host}/api/public/otel"
    OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
  } : { APP_ENV = "production" }
  gateway_env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    VERTEX_LOCATION      = var.vertex_location
    LANGFUSE_HOST        = var.langfuse_host
  }
}

resource "google_service_account" "app" {
  account_id   = local.sa_id
  display_name = "${local.name}: the app and its gateway"
}

# For an agent: call the models on Agent Platform, and nothing else in the project.
resource "google_project_iam_member" "models" {
  count   = local.gateway ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = google_service_account.app.member
}

# The keys' secrets, with no version. A person adds each value as a version before start_app.
resource "google_secret_manager_secret" "keys" {
  for_each  = local.key_names
  secret_id = "${local.name}-${each.key}"
  replication {
    auto {
      dynamic "customer_managed_encryption" {
        for_each = var.kms_key == null ? [] : [var.kms_key]
        content {
          kms_key_name = customer_managed_encryption.value
        }
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = local.key_names
  secret_id = google_secret_manager_secret.keys[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.app.member
}

# An HTTP service: one instance (its state database has one writer), behind the client's load balancer.
resource "google_cloud_run_v2_service" "app" {
  count               = local.service && var.start_app ? 1 : 0
  name                = local.name
  location            = var.region
  ingress             = var.ingress
  deletion_protection = var.deletion_protection
  # An agent checks each caller's OIDC token itself (AGENT_IDENTITY=oidc), so Cloud Run's own IAM check would ask for a
  # second, Google-issued token in the same header; a project without that check keeps Cloud Run's.
  invoker_iam_disabled = local.gateway

  template {
    service_account                  = google_service_account.app.email
    max_instance_request_concurrency = 20
    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      name       = "app"
      image      = var.agent_image
      args       = length(local.s.args) > 0 ? local.s.args : null
      depends_on = local.gateway ? ["gateway"] : null
      ports {
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
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.keys[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = local.s.health
          port = local.s.port
        }
        period_seconds    = 5
        failure_threshold = 24
      }
      liveness_probe {
        http_get {
          path = local.s.health
          port = local.s.port
        }
        period_seconds = 30
      }
      resources {
        limits = { cpu = var.resources.agent_cpu, memory = var.resources.agent_memory }
      }
    }

    dynamic "containers" {
      for_each = local.gateway ? ["gateway"] : []
      content {
        name  = "gateway"
        image = var.gateway_image
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
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.keys[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
        startup_probe {
          http_get {
            path = "/health/liveliness"
            port = 4000
          }
          period_seconds    = 5
          failure_threshold = 24
        }
        resources {
          limits = { cpu = var.resources.gateway_cpu, memory = var.resources.gateway_memory }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.read, google_project_iam_member.models]

  lifecycle {
    precondition {
      condition     = !local.gateway || (var.gateway_image != "" && var.oidc_issuer != "" && var.oidc_audience != "" && var.langfuse_host != "")
      error_message = "An agent needs gateway_image, oidc_issuer, oidc_audience and langfuse_host."
    }
  }
}

# A project that runs to completion: a Cloud Run job, which runs only when someone executes it. It runs the image's
# own command.
resource "google_cloud_run_v2_job" "app" {
  count               = local.service ? 0 : 1
  name                = local.name
  location            = var.region
  deletion_protection = var.deletion_protection
  template {
    task_count = 1
    template {
      service_account = google_service_account.app.email
      max_retries     = 0
      timeout         = "3600s"
      containers {
        image = var.agent_image
        env {
          name  = "APP_ENV"
          value = "production"
        }
        resources {
          limits = { cpu = var.resources.agent_cpu, memory = var.resources.agent_memory }
        }
      }
    }
  }
}
