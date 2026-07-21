---
id: TASK-003
title: "Wire Secret Manager Mounts into Cloud Run v2 Service Templates"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Wire Secret Manager Mounts into Cloud Run v2 Service Templates

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

`infra/terraform/modules/cloud_run/main.tf` currently contains this comment inside the `containers` block:

> *"Non-sensitive runtime config; secrets are mounted via Secret Manager bindings added in Task 008 (us_001) once all secrets are defined."*

This task fulfils that deferred item. Cloud Run v2 exposes secrets as environment variables via `value_source.secret_key_ref`. The approach uses a `dynamic "env"` block driven by a local service→secret mapping, so no per-service Terraform resource is needed — the existing `for_each` loop handles all services.

The canonical list of which secrets each service requires is defined in `secrets/iam.tf` (TASK-002). To avoid duplication (DRY), the `cloud_run` module consumes a `secret_names` variable (a `map(string)` of logical name → Secret Manager secret_id). The per-service env-var mapping is co-located in `cloud_run/main.tf` alongside the service sizing map it accompanies.

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **Scenario 3** | Cloud Run services pick up the new secret value within 60 s of the next request after rotation — environment variable mounts via `latest` version satisfy this |
| **DoD** | Cloud Run services use `secretenv` to access secrets at runtime |

---

## Implementation Steps

### 1. Add `secret_names` variable to `infra/terraform/modules/cloud_run/variables.tf`

```hcl
variable "secret_names" {
  type        = map(string)
  description = "Map of logical secret name to Secret Manager secret_id (short name). Passed from the secrets module output."
  default     = {}
}
```

Using `default = {}` allows the module to be applied before the secrets module exists (e.g., in isolation during bootstrapping), avoiding a hard dependency ordering problem.

### 2. Add per-service secret env-var map local to `infra/terraform/modules/cloud_run/main.tf`

Add the following `locals` block directly below the existing `services` map closing brace:

```hcl
# ── Per-service Secret Manager env-var bindings ──────────────────────────────
# Each entry maps a Cloud Run env-var name to a logical secret key in var.secret_names.
# Only secrets that exist in var.secret_names are mounted (try() guards against
# missing keys during first bootstrapping apply before secrets module runs).
locals {
  service_secret_env_vars = {
    "api-gateway" = [
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
  }
}
```

### 3. Add `dynamic "env"` secret mounts inside the `containers` block in `cloud_run/main.tf`

Locate the `containers` block inside `google_cloud_run_v2_service.services`. Directly after the existing plain `env` blocks (for `ENVIRONMENT`, `GCP_PROJECT_ID`, `REGION`), add:

```hcl
      # ── Secret Manager env var mounts ─────────────────────────────────────
      # Iterates over the per-service secret map. try() guards against a missing
      # secret_names entry during initial bootstrap before the secrets module runs.
      dynamic "env" {
        for_each = {
          for item in try(local.service_secret_env_vars[each.key], []) :
          item.env_name => item
          if contains(keys(var.secret_names), item.secret_key)
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = var.secret_names[env.value.secret_key]
              version = "latest"
            }
          }
        }
      }
```

**Note:** Using `version = "latest"` is what enables Scenario 3 (rotation without redeployment). Cloud Run resolves `latest` on each new instance start and on every request when `cpu_idle = false`.

---

## Files Modified / Created

| File | Action |
|---|---|
| `infra/terraform/modules/cloud_run/variables.tf` | Add `secret_names` variable |
| `infra/terraform/modules/cloud_run/main.tf` | Add `service_secret_env_vars` local; add `dynamic "env"` block in `containers` |

---

## Verification

```bash
cd infra/terraform/environments/dev
terraform plan | grep "secret_key_ref"
# Expected: Multiple occurrences — one per (service, secret) binding

# After apply — confirm secret env var on api-gateway:
gcloud run services describe api-gateway-dev \
  --region=us-central1 --project=smarthandoff-dev \
  --format="json" \
  | jq '.spec.template.spec.containers[0].env[] | select(.valueFrom.secretKeyRef != null)'
# Expected: JWT_SIGNING_KEY_PRIVATE, JWT_SIGNING_KEY_PUBLIC, OIDC_* entries
```
