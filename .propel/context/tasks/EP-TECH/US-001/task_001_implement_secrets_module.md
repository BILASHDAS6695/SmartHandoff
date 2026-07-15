---
id: TASK-001
title: "Implement `secrets` Terraform Module — Secret Manager Placeholder Secrets"
user_story: US-001
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

# TASK-001: Implement `secrets` Terraform Module — Secret Manager Placeholder Secrets

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

The `infra/terraform/modules/secrets/main.tf` is currently a stub with the comment:

> *"Full implementation: EP-TECH/us_001/task_008_secret_manager.md"*

`secrets/outputs.tf` is also empty. The `cloud_run` module explicitly defers all secret injection:

> *"Non-sensitive runtime config; secrets are mounted via Secret Manager bindings added in Task 008"*

This task delivers the complete Secret Manager Terraform module required to satisfy **Acceptance Criterion 4** (no plaintext secrets in source or environment variables) and the DoD item: *"Secret Manager contains placeholder secrets for all services"*.

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 4** | Zero plaintext secrets in Cloud Run env vars or container layers; all secrets mounted from Secret Manager |

---

## Implementation Steps

### 1. Author `infra/terraform/modules/secrets/main.tf`

> **Important scoping note**: The `cloud_sql` module already creates and manages the `smarthandoff-db-password-<environment>` secret via `google_secret_manager_secret.db_password` with the actual `random_password` value. The `secrets` module must **not** re-create it (doing so causes a resource naming conflict). The `secrets` module owns all other application secrets.

Create one `google_secret_manager_secret` + `google_secret_manager_secret_version` pair for **each** of the following secrets. Use a `for_each` over a `locals` map to avoid repetition.

| Secret Name (key) | Consumed by Service(s) | Placeholder Value |
|---|---|---|
| `redis-auth-token` | api-gateway, coordinator-agent, ml-inference | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |
| `jwt-signing-key` | api-gateway | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |
| `fhir-api-key` | coordinator-agent, docs-agent, medrecon-agent | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |
| `twilio-auth-token` | comms-agent, notification-svc | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |
| `sendgrid-api-key` | comms-agent, notification-svc | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |
| `hl7-mllp-signing-key` | hl7-listener | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |
| `vertex-ai-api-key` | ml-inference, coordinator-agent | `PLACEHOLDER_CHANGE_BEFORE_DEPLOY` |

Secret resource naming convention: `smarthandoff-<secret-name>-<environment>` (e.g., `smarthandoff-jwt-signing-key-dev`).

**CMEK for secrets**: Use the Cloud KMS crypto key already created by the `cloud_sql` module (passed in via `var.kms_key_id`, which maps to `module.cloud_sql.sql_cmek_key_id`).

```hcl
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
}

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
}

resource "google_secret_manager_secret_version" "placeholder" {
  for_each    = google_secret_manager_secret.secrets
  secret      = each.value.id
  secret_data = "PLACEHOLDER_CHANGE_BEFORE_DEPLOY"

  lifecycle {
    # Prevent Terraform from overwriting secrets updated outside IaC (e.g., via CI/CD secret rotation)
    ignore_changes = [secret_data]
  }
}
```

### 2. Author IAM Bindings in `infra/terraform/modules/secrets/main.tf`

Define a map of `service → [list of secrets it needs from this module]`. The `db-password` IAM binding is already in `cloud_sql/main.tf` — do not duplicate it here.

```hcl
locals {
  service_secret_bindings = {
    "api-gateway"        = ["redis-auth-token", "jwt-signing-key"]
    "hl7-listener"       = ["hl7-mllp-signing-key"]
    "coordinator-agent"  = ["fhir-api-key", "vertex-ai-api-key"]
    "docs-agent"         = ["fhir-api-key"]
    "medrecon-agent"     = ["fhir-api-key"]
    "comms-agent"        = ["twilio-auth-token", "sendgrid-api-key"]
    "ml-inference"       = ["vertex-ai-api-key", "redis-auth-token"]
    "notification-svc"   = ["twilio-auth-token", "sendgrid-api-key"]
  }

  # Flatten to list of {service, secret} pairs
  bindings_flat = flatten([
    for svc, secrets in local.service_secret_bindings : [
      for s in secrets : { service = svc, secret = s }
    ]
  ])
}

resource "google_secret_manager_secret_iam_member" "service_access" {
  for_each = {
    for b in local.bindings_flat : "${b.service}/${b.secret}" => b
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_accounts[each.value.service]}"
}
```

### 3. Update `infra/terraform/modules/secrets/variables.tf`

Add the following variables (`project_id`, `environment`, `service_accounts` already exist):

```hcl
variable "region" {
  type        = string
  description = "GCP region for secret replication"
}

variable "kms_key_id" {
  type        = string
  description = "Cloud KMS crypto key ID (from cloud_sql module: sql_cmek_key_id) for CMEK encryption of secrets at rest"
}
```

### 4. Update `infra/terraform/modules/secrets/outputs.tf`

```hcl
output "secret_ids" {
  description = "Map of secret key → Secret Manager resource ID"
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.id }
}

output "secret_versions" {
  description = "Map of secret key → latest version resource name"
  value       = { for k, v in google_secret_manager_secret_version.placeholder : k => v.name }
}
```

---

## Definition of Done

- [ ] `secrets/main.tf` implements all 9 secret resources with CMEK replication and `ignore_changes = [secret_data]`
- [ ] IAM bindings grant `roles/secretmanager.secretAccessor` to each Cloud Run SA for only its required secrets (principle of least privilege)
- [ ] `secrets/variables.tf` includes `region` and `kms_key_id` variables with descriptions
- [ ] `secrets/outputs.tf` exposes `secret_ids` and `secret_versions` maps
- [ ] `terraform validate` passes for the `secrets` module in isolation
- [ ] No plaintext real credentials in any `.tf` or `.tfvars` file (placeholder values only)
- [ ] KMS key granted `roles/cloudkms.cryptoKeyEncrypterDecrypter` to Secret Manager service agent before secret creation (`depends_on`)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `cloud_sql` module | Module output | `sql_cmek_key_id` passed in to reuse existing KMS key for CMEK encryption |
| `cloud_run` module | Module output | `service_accounts` map passed to IAM bindings |

> **Key scoping note**: `cloud_sql` already owns the `db-password` secret + its IAM binding. The `secrets` module owns all remaining application secrets.

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/modules/secrets/main.tf` | Replace stub — full implementation |
| `infra/terraform/modules/secrets/outputs.tf` | Replace stub — add outputs |
| `infra/terraform/modules/secrets/variables.tf` | Update — add `region`, `kms_key_id` |
