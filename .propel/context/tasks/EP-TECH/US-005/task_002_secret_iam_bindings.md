---
id: TASK-002
title: "Implement Per-Service Secret Manager IAM Bindings (Least Privilege)"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-002: Implement Per-Service Secret Manager IAM Bindings (Least Privilege)

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-005 technical notes explicitly require:

> *"Use `secretmanager.SecretAccessor` role on individual secret resources, NOT at the project level"*

Each Cloud Run service account must be granted `roles/secretmanager.secretAccessor` only on the specific secrets it needs — not on the project, not on all secrets. This task adds `google_secret_manager_secret_iam_member` resources to `infra/terraform/modules/secrets/main.tf` (or a dedicated `secrets/iam.tf` for separation of concerns).

The service account emails are passed in from the environment root via the `service_accounts` variable already declared in TASK-001.

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **DoD** | IAM: each Cloud Run service account has `secretmanager.secretAccessor` only for its own secrets (principle of least privilege) |

---

## Implementation Steps

### 1. Define the per-service secret access matrix in `infra/terraform/modules/secrets/iam.tf`

Create a new file `infra/terraform/modules/secrets/iam.tf`. Using a local map keeps the access matrix readable and avoids repetitive `resource` blocks.

```hcl
# ── Per-service secret access matrix ────────────────────────────────────────
# Each service is granted secretAccessor ONLY on the secrets it requires.
# The role is bound at the individual secret resource level — never at project level.
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
  }

  # Flatten the matrix into a list of {service, secret_key} pairs for for_each.
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

# ── Bind secretAccessor to each (service, secret) pair ──────────────────────
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
```

### 2. Verify no project-level bindings exist

After apply, confirm no broad project-level `secretmanager.secretAccessor` binding has been created:

```bash
gcloud projects get-iam-policy smarthandoff-dev \
  --format=json | jq '.bindings[] | select(.role == "roles/secretmanager.secretAccessor")'
# Expected: no output (empty)
```

---

## Files Modified / Created

| File | Action |
|---|---|
| `infra/terraform/modules/secrets/iam.tf` | Create with per-service secret access matrix and IAM bindings |

---

## Verification

```bash
cd infra/terraform/environments/dev
terraform plan | grep "google_secret_manager_secret_iam_member"
# Expected: N resources to add where N = total (service, secret) pairs in the matrix

# After apply — spot check api-gateway:
gcloud secrets get-iam-policy smarthandoff-jwt-signing-key-private-dev \
  --project=smarthandoff-dev --format=json \
  | jq '.bindings[] | select(.role == "roles/secretmanager.secretAccessor")'
# Expected: member = "serviceAccount:cr-api-gateway-dev@smarthandoff-dev.iam.gserviceaccount.com"
```
