---
id: TASK-001
title: "Implement `secrets` Terraform Module — Declare All Secret Manager Secrets"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: []
---

# TASK-001: Implement `secrets` Terraform Module — Declare All Secret Manager Secrets

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

`infra/terraform/modules/secrets/main.tf` is currently a two-line stub:

```hcl
# secrets module — stub
# Full implementation: EP-TECH/us_001/task_008_secret_manager.md
```

`secrets/variables.tf` declares only `project_id`, `environment`, and `service_accounts`. `secrets/outputs.tf` is also a stub comment. This task fully implements the module by declaring all `google_secret_manager_secret` and `google_secret_manager_secret_version` resources with placeholder values, and emitting the secret IDs needed by TASK-002 and TASK-003.

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **Scenario 1** | All required secret names exist with at least one version in ENABLED state after `terraform apply` |

---

## Implementation Steps

### 1. Add variables to `infra/terraform/modules/secrets/variables.tf`

Replace the existing three-variable stub with the full variable set:

```hcl
variable "project_id"  { type = string }
variable "environment" { type = string }
variable "region"      { type = string }

# Map of Cloud Run service name → service account email.
# Used in TASK-002 to scope secretAccessor IAM bindings per secret.
variable "service_accounts" {
  type        = map(string)
  description = "Map of Cloud Run service name to service account email."
}
```

### 2. Implement `infra/terraform/modules/secrets/main.tf`

Replace the stub with the full resource declarations below. All `secret_data` values use placeholder strings; SecOps populates real values post-apply (documented in BOOTSTRAP.md Step 3).

```hcl
locals {
  # Canonical secret definitions. Each entry drives one google_secret_manager_secret
  # and one placeholder google_secret_manager_secret_version.
  # Key = logical name (used in outputs), value = secret ID suffix.
  secrets = {
    db_password              = "smarthandoff-db-password-${var.environment}"
    fhir_client_secret       = "smarthandoff-fhir-client-secret-${var.environment}"
    fhir_client_id           = "smarthandoff-fhir-client-id-${var.environment}"
    fhir_base_url            = "smarthandoff-fhir-base-url-${var.environment}"
    twilio_auth_token        = "smarthandoff-twilio-auth-token-${var.environment}"
    twilio_account_sid       = "smarthandoff-twilio-account-sid-${var.environment}"
    twilio_verify_service_sid = "smarthandoff-twilio-verify-service-sid-${var.environment}"
    twilio_phone_number      = "smarthandoff-twilio-phone-number-${var.environment}"
    sendgrid_api_key         = "smarthandoff-sendgrid-api-key-${var.environment}"
    jwt_signing_key_private  = "smarthandoff-jwt-signing-key-private-${var.environment}"
    jwt_signing_key_public   = "smarthandoff-jwt-signing-key-public-${var.environment}"
    oidc_client_id           = "smarthandoff-oidc-client-id-${var.environment}"
    oidc_client_secret       = "smarthandoff-oidc-client-secret-${var.environment}"
    oidc_discovery_url       = "smarthandoff-oidc-discovery-url-${var.environment}"
    phi_encryption_key       = "smarthandoff-phi-encryption-key-${var.environment}"
    phi_encryption_key_det   = "smarthandoff-phi-encryption-key-det-${var.environment}"
    gcs_hmac_key             = "smarthandoff-gcs-hmac-key-${var.environment}"
    vertex_ai_project        = "smarthandoff-vertex-ai-project-${var.environment}"
    slack_webhook_url        = "smarthandoff-slack-webhook-url-${var.environment}"
  }
}

# ── Secret Manager secrets ───────────────────────────────────────────────────
resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secrets
  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ── Placeholder versions — SecOps replaces via bootstrap script ──────────────
# sensitive = true prevents the placeholder value from appearing in plan output.
resource "google_secret_manager_secret_version" "placeholders" {
  for_each    = google_secret_manager_secret.secrets
  secret      = each.value.id
  secret_data = "PLACEHOLDER_REPLACE_BEFORE_USE"

  # Prevent Terraform from destroying versions if the placeholder has been
  # replaced with a real value outside of Terraform.
  lifecycle {
    ignore_changes = [secret_data]
  }
}
```

**Note:** `sensitive = true` is not a valid argument on `google_secret_manager_secret_version`; instead mark output values `sensitive = true` (see Step 3). The `lifecycle { ignore_changes = [secret_data] }` block ensures Terraform does not overwrite real values after the initial apply.

### 3. Implement `infra/terraform/modules/secrets/outputs.tf`

Replace the stub comment with secret ID outputs used by TASK-002 (IAM) and TASK-003 (Cloud Run mounts):

```hcl
# Emit the fully-qualified secret resource IDs for use in IAM bindings and
# Cloud Run secret env var references. Values are marked sensitive so they
# do not appear in terraform output without the -json flag.

output "secret_ids" {
  description = "Map of logical secret name to Secret Manager resource ID."
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.id }
  sensitive   = true
}

output "secret_names" {
  description = "Map of logical secret name to Secret Manager secret_id (short name)."
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.secret_id }
}
```

---

## Files Modified / Created

| File | Action |
|---|---|
| `infra/terraform/modules/secrets/main.tf` | Replace stub with full resource declarations |
| `infra/terraform/modules/secrets/variables.tf` | Add `region` variable |
| `infra/terraform/modules/secrets/outputs.tf` | Replace stub with `secret_ids` and `secret_names` outputs |

---

## Verification

```bash
cd infra/terraform/environments/dev
terraform plan | grep "google_secret_manager_secret"
# Expected: 19 resources to add (19 secrets + 19 placeholder versions = 38 lines)

terraform apply -auto-approve
gcloud secrets list --project=smarthandoff-dev | wc -l
# Expected: ≥ 19
```
