# ── Per-service Secret Manager IAM bindings (principle of least privilege) ──
# Each Cloud Run service account is granted roles/secretmanager.secretAccessor
# ONLY on the specific secrets it requires. The binding is at the individual
# secret resource level — never at the project level (US-005 technical note).
#
# The service_secret_access map uses the logical secret keys defined in
# local.secrets (main.tf). Only services present in var.service_accounts
# receive bindings — guards against stale entries if a service is removed.

locals {
  # Map of Cloud Run service name → list of logical secret keys (from local.secrets in main.tf)
  service_secret_access = {
    "api-gateway" = [
      "jwt_signing_key_private",
      "jwt_signing_key_public",
      "oidc_client_id",
      "oidc_client_secret",
      "oidc_discovery_url",
    ]
    "hl7-listener" = [
      "db_password",
      "phi_encryption_key",
      "phi_encryption_key_det",
    ]
    "coordinator-agent" = [
      "db_password",
      "fhir_client_id",
      "fhir_client_secret",
      "fhir_base_url",
      "phi_encryption_key",
      "phi_encryption_key_det",
      "vertex_ai_project",
    ]
    "docs-agent" = [
      "db_password",
      "fhir_client_id",
      "fhir_client_secret",
      "fhir_base_url",
      "phi_encryption_key",
      "vertex_ai_project",
      "gcs_hmac_key",
    ]
    "medrecon-agent" = [
      "db_password",
      "fhir_client_id",
      "fhir_client_secret",
      "fhir_base_url",
      "phi_encryption_key",
      "vertex_ai_project",
    ]
    "bed-mgmt-agent" = [
      "db_password",
      "phi_encryption_key",
      "vertex_ai_project",
    ]
    "followup-agent" = [
      "db_password",
      "phi_encryption_key",
      "vertex_ai_project",
      "twilio_auth_token",
      "twilio_account_sid",
      "twilio_verify_service_sid",
      "twilio_phone_number",
      "sendgrid_api_key",
    ]
    "comms-agent" = [
      "db_password",
      "phi_encryption_key",
      "twilio_auth_token",
      "twilio_account_sid",
      "twilio_phone_number",
      "sendgrid_api_key",
    ]
    "ml-inference" = [
      "vertex_ai_project",
      "phi_encryption_key",
    ]
    "notification-svc" = [
      "twilio_auth_token",
      "twilio_account_sid",
      "twilio_verify_service_sid",
      "twilio_phone_number",
      "sendgrid_api_key",
      "slack_webhook_url",
    ]
    "audit-svc" = [
      "db_password",
      "phi_encryption_key",
    ]
    "portal-bff" = [
      "jwt_signing_key_private",
      "jwt_signing_key_public",
      "oidc_client_id",
      "oidc_client_secret",
      "oidc_discovery_url",
      "fhir_client_id",
      "fhir_client_secret",
      "fhir_base_url",
    ]
  }

  # Flatten matrix into a list of {key, service, secret_key} objects for for_each.
  # The composite key uses __ as separator to avoid conflicts with service/secret names.
  secret_iam_bindings = flatten([
    for service, secret_keys in local.service_secret_access : [
      for secret_key in secret_keys : {
        key        = "${service}__${secret_key}"
        service    = service
        secret_key = secret_key
      }
    ]
  ])
}

# ── Bind secretAccessor to each (service, secret) pair ───────────────────────
# Guards:
#  - contains(keys(var.service_accounts), binding.service) → skip if service SA not present
#  - contains(keys(google_secret_manager_secret.secrets), binding.secret_key) is implicit
#    since the secret_key must exist in local.secrets (compilation error otherwise)
resource "google_secret_manager_secret_iam_member" "service_access" {
  for_each = {
    for binding in local.secret_iam_bindings : binding.key => binding
    if contains(keys(var.service_accounts), binding.service)
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret_key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_accounts[each.value.service]}"
}
