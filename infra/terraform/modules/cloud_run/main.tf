# ── Service sizing map ────────────────────────────────────────────────────
locals {
  # Maps each service to the Secret Manager secret keys it requires.
  # Secret names follow the convention: smarthandoff-<key>-<environment>
  # NOTE: db-password is managed by the cloud_sql module; its secret name is
  #       "smarthandoff-db-password-<environment>" — referenced directly here.
  service_secrets = {
    "api-gateway" = [
      "db-password", "redis-auth-token", "jwt-signing-key"
    ]
    "hl7-listener" = [
      "hl7-mllp-signing-key"
    ]
    "coordinator-agent" = [
      "db-password", "fhir-api-key", "vertex-ai-api-key"
    ]
    "docs-agent" = [
      "db-password", "fhir-api-key"
    ]
    "medrecon-agent" = [
      "db-password", "fhir-api-key"
    ]
    "bed-mgmt-agent" = [
      "db-password"
    ]
    "followup-agent" = [
      "db-password"
    ]
    "comms-agent" = [
      "db-password", "twilio-auth-token", "sendgrid-api-key"
    ]
    "ml-inference" = [
      "vertex-ai-api-key", "redis-auth-token"
    ]
    "notification-svc" = [
      "twilio-auth-token", "sendgrid-api-key"
    ]
  }

  # Derive the env var name from the secret key (e.g., "db-password" → "DB_PASSWORD")
  secret_env_var_name = {
    "db-password"          = "DB_PASSWORD"
    "redis-auth-token"     = "REDIS_AUTH_TOKEN"
    "jwt-signing-key"      = "JWT_SIGNING_KEY"
    "fhir-api-key"         = "FHIR_API_KEY"
    "twilio-auth-token"    = "TWILIO_AUTH_TOKEN"
    "sendgrid-api-key"     = "SENDGRID_API_KEY"
    "hl7-mllp-signing-key" = "HL7_MLLP_SIGNING_KEY"
    "vertex-ai-api-key"    = "VERTEX_AI_API_KEY"
  }

  # Matches Design §9.2 exactly.
  # cpu_idle = false for api-gateway and coordinator-agent (latency-sensitive);
  # all agents use cpu_idle = true to reduce costs during low-traffic periods.
  services = {
    "api-gateway" = {
      min         = 2
      max         = 20
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 100
      cpu_idle    = false
    }
    "hl7-listener" = {
      min         = 1
      max         = 10
      cpu         = "1000m"
      memory      = "512Mi"
      concurrency = 50
      cpu_idle    = false
    }
    "coordinator-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 20
      cpu_idle    = false
    }
    "docs-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "4Gi"
      concurrency = 5
      cpu_idle    = true
    }
    "medrecon-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 10
      cpu_idle    = true
    }
    "bed-mgmt-agent" = {
      min         = 1
      max         = 5
      cpu         = "1000m"
      memory      = "1Gi"
      concurrency = 20
      cpu_idle    = true
    }
    "followup-agent" = {
      min         = 1
      max         = 10
      cpu         = "1000m"
      memory      = "1Gi"
      concurrency = 20
      cpu_idle    = true
    }
    "comms-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 10
      cpu_idle    = true
    }
    "ml-inference" = {
      min         = 1
      max         = 5
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 50
      cpu_idle    = true
    }
    "notification-svc" = {
      min         = 1
      max         = 5
      cpu         = "1000m"
      memory      = "512Mi"
      concurrency = 50
      cpu_idle    = true
    }
  }
}

# ── Dedicated service account per Cloud Run service ──────────────────────
resource "google_service_account" "cloud_run_sa" {
  for_each = local.services

  account_id   = "cr-${each.key}-${var.environment}"
  display_name = "Cloud Run SA: ${each.key} (${var.environment})"
  project      = var.project_id
}

# ── Cloud Run v2 services ────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "services" {
  for_each = local.services

  name     = "${each.key}-${var.environment}"
  location = var.region
  project  = var.project_id

  # Only the API Gateway is reachable from the public internet.
  # All other services (agents, HL7 listener, etc.) are internal only.
  ingress = each.key == "api-gateway" ? "INGRESS_TRAFFIC_ALL" : "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.cloud_run_sa[each.key].email

    scaling {
      min_instance_count = each.value.min
      max_instance_count = each.value.max
    }

    max_instance_request_concurrency = each.value.concurrency

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      # Placeholder image — CI/CD (Cloud Deploy) replaces this on first real deploy.
      # lifecycle.ignore_changes below prevents Terraform from reverting CI/CD updates.
      image = "us-docker.pkg.dev/cloudrun/container/hello"

      resources {
        limits = {
          cpu    = each.value.cpu
          memory = each.value.memory
        }
        cpu_idle          = each.value.cpu_idle
        startup_cpu_boost = true
      }

      # Liveness probe — triggers container restart on 3 consecutive failures.
      # hl7-listener is a raw TCP MLLP server (port 2575) — no HTTP server present.
      # All other services expose GET /health returning {"status":"ok"}.
      liveness_probe {
        dynamic "http_get" {
          for_each = each.key != "hl7-listener" ? [1] : []
          content {
            path = "/health"
          }
        }
        dynamic "tcp_socket" {
          for_each = each.key == "hl7-listener" ? [1] : []
          content {
            port = 2575
          }
        }
        period_seconds    = 10
        failure_threshold = 3
      }

      # Startup probe — blocks traffic during cold-start initialisation.
      # failure_threshold=12 with period=5 → 60-second window for LangChain agents
      # (docs-agent, medrecon-agent, coordinator-agent, ml-inference).
      startup_probe {
        dynamic "http_get" {
          for_each = each.key != "hl7-listener" ? [1] : []
          content {
            path = "/ready"
          }
        }
        dynamic "tcp_socket" {
          for_each = each.key == "hl7-listener" ? [1] : []
          content {
            port = 2575
          }
        }
        period_seconds    = 5
        failure_threshold = 12 # 60-second startup window
      }

      # Readiness probe — sheds traffic from running instances that have lost
      # upstream dependencies (DB pool exhausted, Redis timeout) without
      # triggering a restart. Fires continuously post-startup (distinct from
      # startup_probe which is one-shot during initialisation).
      # Returns {"status":"ready"} only after DB + Redis are reachable.
      readiness_probe {
        dynamic "http_get" {
          for_each = each.key != "hl7-listener" ? [1] : []
          content {
            path = "/ready"
          }
        }
        dynamic "tcp_socket" {
          for_each = each.key == "hl7-listener" ? [1] : []
          content {
            port = 2575
          }
        }
        period_seconds    = 10
        failure_threshold = 3
        # initial_delay_seconds intentionally omitted — startup_probe already
        # covers the startup window; readiness_probe fires post-startup only.
      }

      # Non-sensitive runtime config
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }

      # Secret Manager bindings — one env var per required secret per service.
      # Secret names follow the convention: smarthandoff-<key>-<environment>
      # No plaintext credentials are set here (satisfies US-001 AC-4 / Scenario 4).
      dynamic "env" {
        for_each = lookup(local.service_secrets, each.key, [])
        content {
          name = local.secret_env_var_name[env.value]
          value_source {
            secret_key_ref {
              secret  = "smarthandoff-${env.value}-${var.environment}"
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    # CI/CD (Cloud Deploy) manages the container image after initial provision.
    # Prevent Terraform from reverting image tags set by Cloud Deploy.
    # Secret versions are rotated outside Terraform via Cloud KMS rotation policy —
    # Terraform should not revert to "latest" on every plan.
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
  }

  depends_on = [google_service_account.cloud_run_sa]
}
