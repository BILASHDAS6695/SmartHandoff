---
task_id: task_008
story_id: us_001
epic: EP-TECH
title: Secret Manager — Secrets, IAM Bindings, and Cloud Run Secret Mounts
layer: Security / Secrets
effort_hours: 1.5
sequence: 8
status: Draft
---

# TASK-008: Secret Manager — Secrets, IAM Bindings, and Cloud Run Secret Mounts

> **Story:** EP-TECH/US-001 | **Layer:** Security / Secrets | **Effort:** 1.5 hours | **Seq:** 8 of 11

## Objective

Create all required Secret Manager secrets with placeholder values, bind each Cloud Run service account to only the secrets it needs (least privilege), and configure Cloud Run services to mount secrets as environment variables — ensuring zero hardcoded credentials anywhere in the codebase.

## Implementation Steps

### 1. Secret Definitions (`modules/secrets/main.tf`)

```hcl
locals {
  secrets = {
    # Database
    "db-password"             = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Cloud SQL app user password" }
    "db-connection-string"    = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Full PostgreSQL DSN with private IP" }

    # PHI Encryption Keys (AES-256-GCM)
    "phi-encryption-key"      = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Base64-encoded AES-256 key for PHI fields" }
    "phi-encryption-key-det"  = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Deterministic AES-256 key for MRN lookup" }

    # JWT Signing
    "jwt-signing-key-private" = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "RS256 private key for app JWT signing" }
    "jwt-signing-key-public"  = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "RS256 public key for JWT verification" }

    # OIDC
    "oidc-client-id"          = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Hospital SSO OIDC client ID" }
    "oidc-client-secret"      = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Hospital SSO OIDC client secret" }
    "oidc-discovery-url"      = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "OIDC discovery endpoint URL" }

    # FHIR
    "fhir-base-url"           = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "FHIR R4 base URL" }
    "fhir-client-id"          = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "SMART on FHIR client ID" }
    "fhir-client-secret"      = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "SMART on FHIR client secret" }

    # Vertex AI
    "vertex-ai-project"       = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "GCP project for Vertex AI API calls" }

    # Twilio
    "twilio-account-sid"      = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Twilio account SID" }
    "twilio-auth-token"        = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Twilio auth token" }
    "twilio-verify-service-sid"= { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Twilio Verify service SID for OTP" }
    "twilio-phone-number"      = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "Twilio SMS sender phone number" }

    # SendGrid
    "sendgrid-api-key"        = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "SendGrid API key" }

    # RxNav / Drug Interaction
    "rxnav-base-url"          = { value = "https://rxnav.nlm.nih.gov", description = "RxNav API base URL (public; no key needed)" }
    "openfda-api-key"         = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "OpenFDA API key (optional; increases rate limit)" }

    # Housekeeping / Unit contacts
    "unit-housekeeping-contacts" = { value = "PLACEHOLDER_REPLACE_BY_SECOPS", description = "JSON map of unit → housekeeping phone/email" }
  }
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secrets
  secret_id = "smarthandoff-${each.key}-${var.environment}"
  project   = var.project_id

  replication { auto {} }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_secret_manager_secret_version" "initial" {
  for_each    = local.secrets
  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = each.value.value
  enabled     = true
}
```

### 2. IAM — Least-Privilege Secret Access Per Service

```hcl
locals {
  # Map of service account → list of secrets it may access
  service_secret_access = {
    "api-gateway" = [
      "db-password", "db-connection-string",
      "phi-encryption-key", "phi-encryption-key-det",
      "jwt-signing-key-private", "jwt-signing-key-public",
      "oidc-client-id", "oidc-client-secret", "oidc-discovery-url"
    ]
    "hl7-listener" = ["db-connection-string"]
    "coordinator-agent" = ["db-connection-string"]
    "docs-agent" = [
      "db-connection-string", "phi-encryption-key",
      "fhir-base-url", "fhir-client-id", "fhir-client-secret",
      "vertex-ai-project"
    ]
    "medrecon-agent" = [
      "db-connection-string", "phi-encryption-key",
      "fhir-base-url", "fhir-client-id", "fhir-client-secret",
      "rxnav-base-url", "openfda-api-key"
    ]
    "bed-mgmt-agent" = ["db-connection-string"]
    "followup-agent" = ["db-connection-string", "phi-encryption-key"]
    "comms-agent" = [
      "db-connection-string", "phi-encryption-key",
      "vertex-ai-project"
    ]
    "ml-inference" = ["db-connection-string"]
    "notification-svc" = [
      "twilio-account-sid", "twilio-auth-token",
      "twilio-verify-service-sid", "twilio-phone-number",
      "sendgrid-api-key", "unit-housekeeping-contacts"
    ]
  }
}

resource "google_secret_manager_secret_iam_member" "secret_access" {
  for_each = {
    for entry in flatten([
      for service, secrets in local.service_secret_access : [
        for secret in secrets : {
          key     = "${service}--${secret}"
          service = service
          secret  = secret
        }
      ]
    ]) : entry.key => entry
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_accounts[each.value.service]}"
}
```

### 3. Cloud Run Secret Mounts — Example for `api-gateway`

These env-var-from-secret bindings are added to the Cloud Run service definition in Task 003 (or as a separate update resource):

```hcl
# In modules/cloud_run/main.tf → containers block for api-gateway
env {
  name = "DB_PASSWORD"
  value_source {
    secret_key_ref {
      secret  = "smarthandoff-db-password-${var.environment}"
      version = "latest"
    }
  }
}
env {
  name = "PHI_ENCRYPTION_KEY"
  value_source {
    secret_key_ref {
      secret  = "smarthandoff-phi-encryption-key-${var.environment}"
      version = "latest"
    }
  }
}
# ... (repeat for each secret this service needs)
```

## Acceptance Criteria

- [ ] `gcloud secrets list --project={PROJECT} --filter="labels.environment={env}"` shows all 21 secrets created
- [ ] All secrets have version `1` with status `ENABLED`; value = "PLACEHOLDER_REPLACE_BY_SECOPS"
- [ ] IAM: `gcloud secrets get-iam-policy smarthandoff-twilio-auth-token-dev` shows ONLY `notification-svc` service account has `secretAccessor` — NO other service account in the binding
- [ ] `gcloud secrets get-iam-policy smarthandoff-db-password-dev` shows `api-gateway`, `hl7-listener`, and agent SAs — but NOT `notification-svc`
- [ ] Cloud Run service `api-gateway-dev` lists `DB_PASSWORD` as an environment variable sourced from Secret Manager (visible in `gcloud run services describe`)
- [ ] Zero secrets appear in `terraform show` output (outputs must not include secret values; use `sensitive = true` attribute)

## Files to Create

```
infra/terraform/modules/secrets/main.tf
infra/terraform/modules/secrets/variables.tf
infra/terraform/modules/secrets/outputs.tf
infra/terraform/modules/secrets/README.md
```

## SecOps Handoff Note

After `terraform apply`, SecOps must update all PLACEHOLDER values:
```bash
echo -n "actual-db-password" | gcloud secrets versions add \
  smarthandoff-db-password-{env} --data-file=-
```
This is documented in `infra/BOOTSTRAP.md`.

## Notes

- `sensitive = true` on all Terraform outputs that reference secret data — prevents values appearing in `terraform output` or logs
- Secret version `latest` in Cloud Run bindings ensures service picks up new versions on next revision deploy — no container rebuild needed for credential rotation
- Never store actual secret values in `terraform.tfvars` or any file committed to git
