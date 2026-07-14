---
id: TASK-003
title: "Wire `secrets` Module into Dev, Staging, and Production Environment Root Configurations"
user_story: US-001
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-003: Wire `secrets` Module into Dev, Staging, and Production Environment Root Configurations

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

The three environment root configurations (`environments/dev/main.tf`, `environments/staging/main.tf`, `environments/prod/main.tf`) do not reference the `secrets` Terraform module. Without this wiring:

1. Secret Manager secrets are never provisioned (TASK-001 work is unreachable)
2. Cloud Run IAM bindings granting `secretAccessor` to service accounts are never applied
3. `terraform plan` on any environment will not create any Secret Manager resources

This task adds the `module "secrets"` block to all three environment roots and ensures the `monitoring` stub module is also referenced (to prevent `terraform plan` errors from unresolved module references in the same root).

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 1** | `When` `terraform apply` is executed for the dev environment, `Then` all resources including Secret Manager secrets are created with zero manual console steps |
| **Scenario 4** | Secret Manager IAM bindings must be active before services deploy |

---

## Implementation Steps

### 1. Add `module "secrets"` to `environments/dev/main.tf`

Insert the following block **after** `module "cloud_sql"` and **before** any closing comments:

```hcl
# ── Secret Manager ────────────────────────────────────────────────────
module "secrets" {
  source      = "../../modules/secrets"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  # Reuse the KMS crypto key already created by the cloud_sql module for CMEK encryption
  kms_key_id = module.cloud_sql.sql_cmek_key_id

  # Grant each Cloud Run service account access to its required secrets
  service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_run, module.cloud_sql]
}
```

### 2. Verify `sql_cmek_key_id` Output Exists in `cloud_sql` Module

The `cloud_sql` module already exports `sql_cmek_key_id` (confirmed in `modules/cloud_sql/outputs.tf`). No change is required to that file. The output value is `google_kms_crypto_key.sql_cmek.id`.

### 3. Apply the Same `module "secrets"` Block to `environments/staging/main.tf`

The staging root uses an identical module reference pattern. Copy the `module "secrets"` block verbatim.

### 4. Apply the Same `module "secrets"` Block to `environments/prod/main.tf`

The prod root uses an identical module reference pattern. Copy the `module "secrets"` block verbatim.

### 5. Verify Module Dependency Order

Ensure `depends_on` chain is complete for a clean `terraform apply`:

```
google_project_service.apis
  → module.networking
    → module.cloud_run
      → module.pubsub
    → module.cloud_sql
      → module.storage
      → module.secrets       ← NEW
    → module.redis
  → module.armor_lb_cdn
```

`module.secrets` depends on both `module.cloud_run` (for SA emails) and `module.cloud_sql` (for the KMS key). This guarantees correct provisioning order.

---

## Definition of Done

- [ ] `module "secrets"` block present in `environments/dev/main.tf`
- [ ] `module "secrets"` block present in `environments/staging/main.tf`
- [ ] `module "secrets"` block present in `environments/prod/main.tf`
- [ ] `kms_key_id = module.cloud_sql.sql_cmek_key_id` correctly references the existing KMS output
- [ ] `depends_on = [module.cloud_run, module.cloud_sql]` declared on the secrets module block
- [ ] `terraform validate` passes for all three environments after adding the block
- [ ] No environment root references the `monitoring` stub module yet (deferred to US-003 per stub comment)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Preceding task | `secrets` module `main.tf` must exist before environments can reference it |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/environments/dev/main.tf` | Add `module "secrets"` block |
| `infra/terraform/environments/staging/main.tf` | Add `module "secrets"` block |
| `infra/terraform/environments/prod/main.tf` | Add `module "secrets"` block |
| `infra/terraform/modules/cloud_sql/outputs.tf` | Add `kms_cmek_key_id` output if missing |
