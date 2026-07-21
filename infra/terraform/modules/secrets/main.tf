# ── Application secrets (placeholder values) ────────────────────────────
# Managed by: EP-TECH / US-001 / TASK-001
# NOTE: The cloud_sql module owns smarthandoff-db-password-<env>.
#       This module manages all other application secrets only.

locals {
  secrets = {
    "redis-auth-token"     = {}
    "jwt-signing-key"      = {}
    "fhir-api-key"         = {}
    "twilio-auth-token"    = {}
    "sendgrid-api-key"     = {}
    "hl7-mllp-signing-key" = {}
    "vertex-ai-api-key"    = {}
  }

  # Per-service secret access bindings (db-password IAM is owned by cloud_sql module)
  service_secret_bindings = {
    "api-gateway"       = ["redis-auth-token", "jwt-signing-key"]
    "hl7-listener"      = ["hl7-mllp-signing-key"]
    "coordinator-agent" = ["fhir-api-key", "vertex-ai-api-key"]
    "docs-agent"        = ["fhir-api-key"]
    "medrecon-agent"    = ["fhir-api-key"]
    "comms-agent"       = ["twilio-auth-token", "sendgrid-api-key"]
    "ml-inference"      = ["vertex-ai-api-key", "redis-auth-token"]
    "notification-svc"  = ["twilio-auth-token", "sendgrid-api-key"]
  }

  # Flatten service_secret_bindings into a list of {service, secret} objects
  bindings_flat = flatten([
    for svc, secrets in local.service_secret_bindings : [
      for s in secrets : { service = svc, secret = s }
    ]
  ])
}

# ── Secret Manager secrets (CMEK-encrypted, placeholder values) ───────────
resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secrets
  secret_id = "smarthandoff-${each.key}-${var.environment}"
  project   = var.project_id

  replication {
    user_managed {
      replicas {
        location = var.region
        customer_managed_encryption {
          kms_key_name = var.kms_key_id
        }
      }
    }
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    module      = "secrets"
  }
}

resource "google_secret_manager_secret_version" "placeholder" {
  for_each    = google_secret_manager_secret.secrets
  secret      = each.value.id
  secret_data = "PLACEHOLDER_CHANGE_BEFORE_DEPLOY"

  lifecycle {
    # Prevent Terraform from overwriting secrets rotated outside IaC (e.g., CI/CD secret rotation)
    ignore_changes = [secret_data]
  }
}

# ── IAM: grant each service account secretAccessor on its required secrets ──
resource "google_secret_manager_secret_iam_member" "service_access" {
  for_each = {
    for b in local.bindings_flat : "${b.service}/${b.secret}" => b
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_accounts[each.value.service]}"
}
