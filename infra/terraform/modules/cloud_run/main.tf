# ── Service sizing map ────────────────────────────────────────────────────
locals {
  # ── Per-service Secret Manager env-var bindings ──────────────────────────
  # Each entry maps a Cloud Run env-var name to a logical secret key in var.secret_names.
  # Only secrets that exist in var.secret_names are mounted — try() + contains() guards
  # against missing keys during first bootstrapping apply before the secrets module runs.
  service_secret_env_vars = {
    "api-gateway" = [
      { env_name = "JWT_SIGNING_KEY",         secret_key = "jwt_signing_key" },
      { env_name = "JWT_SIGNING_KEY_PRIVATE", secret_key = "jwt_signing_key_private" },
      { env_name = "JWT_SIGNING_KEY_PUBLIC",  secret_key = "jwt_signing_key_public" },
      { env_name = "OIDC_CLIENT_ID",          secret_key = "oidc_client_id" },
      { env_name = "OIDC_CLIENT_SECRET",      secret_key = "oidc_client_secret" },
      { env_name = "OIDC_DISCOVERY_URL",      secret_key = "oidc_discovery_url" },
    ]
    "hl7-listener" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "PHI_ENCRYPTION_KEY_DET",  secret_key = "phi_encryption_key_det" },
    ]
    "coordinator-agent" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "FHIR_CLIENT_ID",          secret_key = "fhir_client_id" },
      { env_name = "FHIR_CLIENT_SECRET",      secret_key = "fhir_client_secret" },
      { env_name = "FHIR_BASE_URL",           secret_key = "fhir_base_url" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "PHI_ENCRYPTION_KEY_DET",  secret_key = "phi_encryption_key_det" },
      { env_name = "VERTEX_AI_PROJECT",       secret_key = "vertex_ai_project" },
    ]
    "docs-agent" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "FHIR_CLIENT_ID",          secret_key = "fhir_client_id" },
      { env_name = "FHIR_CLIENT_SECRET",      secret_key = "fhir_client_secret" },
      { env_name = "FHIR_BASE_URL",           secret_key = "fhir_base_url" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "VERTEX_AI_PROJECT",       secret_key = "vertex_ai_project" },
      { env_name = "GCS_HMAC_KEY",            secret_key = "gcs_hmac_key" },
    ]
    "medrecon-agent" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "FHIR_CLIENT_ID",          secret_key = "fhir_client_id" },
      { env_name = "FHIR_CLIENT_SECRET",      secret_key = "fhir_client_secret" },
      { env_name = "FHIR_BASE_URL",           secret_key = "fhir_base_url" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "VERTEX_AI_PROJECT",       secret_key = "vertex_ai_project" },
    ]
    "bed-mgmt-agent" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "VERTEX_AI_PROJECT",       secret_key = "vertex_ai_project" },
    ]
    "followup-agent" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "VERTEX_AI_PROJECT",       secret_key = "vertex_ai_project" },
      { env_name = "TWILIO_AUTH_TOKEN",       secret_key = "twilio_auth_token" },
      { env_name = "TWILIO_ACCOUNT_SID",      secret_key = "twilio_account_sid" },
      { env_name = "TWILIO_VERIFY_SID",       secret_key = "twilio_verify_service_sid" },
      { env_name = "TWILIO_PHONE_NUMBER",     secret_key = "twilio_phone_number" },
      { env_name = "SENDGRID_API_KEY",        secret_key = "sendgrid_api_key" },
    ]
    "comms-agent" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
      { env_name = "TWILIO_AUTH_TOKEN",       secret_key = "twilio_auth_token" },
      { env_name = "TWILIO_ACCOUNT_SID",      secret_key = "twilio_account_sid" },
      { env_name = "TWILIO_PHONE_NUMBER",     secret_key = "twilio_phone_number" },
      { env_name = "SENDGRID_API_KEY",        secret_key = "sendgrid_api_key" },
    ]
    "ml-inference" = [
      { env_name = "VERTEX_AI_PROJECT",       secret_key = "vertex_ai_project" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
    ]
    "notification-svc" = [
      { env_name = "TWILIO_AUTH_TOKEN",       secret_key = "twilio_auth_token" },
      { env_name = "TWILIO_ACCOUNT_SID",      secret_key = "twilio_account_sid" },
      { env_name = "TWILIO_VERIFY_SID",       secret_key = "twilio_verify_service_sid" },
      { env_name = "TWILIO_PHONE_NUMBER",     secret_key = "twilio_phone_number" },
      { env_name = "SENDGRID_API_KEY",        secret_key = "sendgrid_api_key" },
      { env_name = "SLACK_WEBHOOK_URL",       secret_key = "slack_webhook_url" },
    ]
    "audit-svc" = [
      { env_name = "DB_PASSWORD",             secret_key = "db_password" },
      { env_name = "PHI_ENCRYPTION_KEY",      secret_key = "phi_encryption_key" },
    ]
    "portal-bff" = [
      { env_name = "JWT_SIGNING_KEY_PRIVATE", secret_key = "jwt_signing_key_private" },
      { env_name = "JWT_SIGNING_KEY_PUBLIC",  secret_key = "jwt_signing_key_public" },
      { env_name = "OIDC_CLIENT_ID",          secret_key = "oidc_client_id" },
      { env_name = "OIDC_CLIENT_SECRET",      secret_key = "oidc_client_secret" },
      { env_name = "OIDC_DISCOVERY_URL",      secret_key = "oidc_discovery_url" },
      { env_name = "FHIR_CLIENT_ID",          secret_key = "fhir_client_id" },
      { env_name = "FHIR_CLIENT_SECRET",      secret_key = "fhir_client_secret" },
      { env_name = "FHIR_BASE_URL",           secret_key = "fhir_base_url" },
    ]
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

      # ── Secret Manager env var mounts ────────────────────────────────────────
      # Secret IDs follow the canonical naming convention:
      #   smarthandoff-{secret_key_with_hyphens}-{environment}
      # e.g., "phi_encryption_key" → "smarthandoff-phi-encryption-key-dev"
      # This approach requires no cross-module reference, avoiding a Terraform
      # cycle between cloud_run and secrets modules (US-005 GAP-1 fix).
      # version = "latest" satisfies US-005 Scenario 3 — Cloud Run resolves
      # the newest enabled version on each new instance start (rotation without
      # redeployment).
      dynamic "env" {
        for_each = {
          for item in try(local.service_secret_env_vars[each.key], []) :
          item.env_name => item
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = "smarthandoff-${replace(env.value.secret_key, "_", "-")}-${var.environment}"
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
    # env is intentionally NOT in ignore_changes — Terraform owns secret mount
    # configuration; CI/CD owns only the image tag.
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  depends_on = [google_service_account.cloud_run_sa]
}
