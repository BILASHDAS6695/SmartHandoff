# ── Application secrets (placeholder values) ────────────────────────────
# Managed by: EP-TECH / US-005
# All secrets declared here use placeholder values on first apply.
# SecOps populates real values after apply — see infra/BOOTSTRAP.md Step 3.
# IAM bindings (per-service secretAccessor grants) are in iam.tf.

locals {
  # Canonical secret definitions.
  # Key = logical name (used in outputs, IAM matrix, Cloud Run mounts).
  # Value = Secret Manager secret_id (what appears in gcloud secrets list).
  secrets = {
    db_password               = "smarthandoff-db-password-${var.environment}"
    fhir_client_secret        = "smarthandoff-fhir-client-secret-${var.environment}"
    fhir_client_id            = "smarthandoff-fhir-client-id-${var.environment}"
    fhir_base_url             = "smarthandoff-fhir-base-url-${var.environment}"
    twilio_auth_token         = "smarthandoff-twilio-auth-token-${var.environment}"
    twilio_account_sid        = "smarthandoff-twilio-account-sid-${var.environment}"
    twilio_verify_service_sid = "smarthandoff-twilio-verify-service-sid-${var.environment}"
    twilio_phone_number       = "smarthandoff-twilio-phone-number-${var.environment}"
    sendgrid_api_key          = "smarthandoff-sendgrid-api-key-${var.environment}"
    jwt_signing_key_private   = "smarthandoff-jwt-signing-key-private-${var.environment}"
    jwt_signing_key_public    = "smarthandoff-jwt-signing-key-public-${var.environment}"
    oidc_client_id            = "smarthandoff-oidc-client-id-${var.environment}"
    oidc_client_secret        = "smarthandoff-oidc-client-secret-${var.environment}"
    oidc_discovery_url        = "smarthandoff-oidc-discovery-url-${var.environment}"
    phi_encryption_key        = "smarthandoff-phi-encryption-key-${var.environment}"
    phi_encryption_key_det    = "smarthandoff-phi-encryption-key-det-${var.environment}"
    gcs_hmac_key              = "smarthandoff-gcs-hmac-key-${var.environment}"
    vertex_ai_project         = "smarthandoff-vertex-ai-project-${var.environment}"
    slack_webhook_url         = "smarthandoff-slack-webhook-url-${var.environment}"
  }
}

# ── Secret Manager secrets (CMEK-encrypted) ──────────────────────────────
resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secrets
  secret_id = each.value
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

# ── Placeholder versions — SecOps replaces via bootstrap script ──────────
# lifecycle.ignore_changes prevents Terraform from overwriting real values
# after initial apply (handles out-of-band rotation via BOOTSTRAP.md Step 3).
resource "google_secret_manager_secret_version" "placeholders" {
  for_each    = google_secret_manager_secret.secrets
  secret      = each.value.id
  secret_data = "PLACEHOLDER_REPLACE_BEFORE_USE"

  lifecycle {
    ignore_changes = [secret_data]
  }
}
