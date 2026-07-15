---
id: TASK-004
title: "Wire `secrets` Module into All Environment Root Modules"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-003]
---

# TASK-004: Wire `secrets` Module into All Environment Root Modules

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

TASK-001 and TASK-002 implement the `secrets` Terraform module. TASK-003 adds a `secret_names` input variable to the `cloud_run` module. This task connects them in all three environment root modules (`dev`, `staging`, `prod`). Currently, none of the `main.tf` environment files reference the `secrets` module.

The secrets module must run after `cloud_run` (to receive service account emails from its output) and the `cloud_run` module must receive `secret_names` from the secrets module output. This creates a circular dependency that must be resolved by the sequencing used in the environment root:

1. Apply `cloud_run` first (service accounts are created; secret mounts are skipped because `secret_names` is empty at this point due to `default = {}`).
2. Apply `secrets` (creates secrets and IAM bindings referencing the service account emails).
3. Re-apply `cloud_run` with `secret_names` populated — Cloud Run revisions are updated to mount the secrets.

In practice, a single `terraform apply` with the module `depends_on` chain handles this correctly because Terraform resolves the dependency graph automatically.

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **Scenario 1** | After `terraform apply` on any environment, all required secrets exist |
| **Scenario 3** | Cloud Run services resolve secrets at runtime via `latest` version |

---

## Implementation Steps

### 1. Add `secrets` module block to `infra/terraform/environments/dev/main.tf`

Add the following block after the `module "cloud_run"` block and before `module "pubsub"`:

```hcl
# ── Secret Manager ────────────────────────────────────────────────────────────
module "secrets" {
  source      = "../../modules/secrets"
  project_id  = var.project_id
  environment = var.environment
  region      = var.region

  # Pass Cloud Run service account emails so the secrets module can bind
  # secretAccessor IAM roles at the individual secret resource level.
  service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_run]
}
```

Then update the `module "cloud_run"` block to pass `secret_names`:

```hcl
module "cloud_run" {
  source           = "../../modules/cloud_run"
  project_id       = var.project_id
  region           = var.region
  environment      = var.environment
  vpc_connector_id = module.networking.vpc_connector_id

  # Secret names are populated after the secrets module runs.
  # On first apply, this defaults to {} and no secret mounts are created.
  # After secrets module is applied, a subsequent plan/apply wires the mounts.
  secret_names = try(module.secrets.secret_names, {})

  depends_on = [module.networking]
}
```

### 2. Repeat for `infra/terraform/environments/staging/main.tf`

Apply the identical changes as Step 1 to the staging environment root module.

### 3. Repeat for `infra/terraform/environments/prod/main.tf`

Apply the identical changes as Step 1 to the prod environment root module.

### 4. Add `region` to environment `variables.tf` if not already present

The `secrets` module requires `var.region`. Confirm it is declared in all three `variables.tf` files. If missing, add:

```hcl
variable "region" {
  type        = string
  description = "GCP region for resource deployments."
  default     = "us-central1"
}
```

---

## Files Modified / Created

| File | Action |
|---|---|
| `infra/terraform/environments/dev/main.tf` | Add `module "secrets"` block; update `module "cloud_run"` to pass `secret_names` |
| `infra/terraform/environments/staging/main.tf` | Same as dev |
| `infra/terraform/environments/prod/main.tf` | Same as dev |
| `infra/terraform/environments/*/variables.tf` | Add `region` variable if missing |

---

## Verification

```bash
cd infra/terraform/environments/dev
terraform validate
# Expected: Success! The configuration is valid.

terraform plan | grep "module.secrets"
# Expected: module.secrets.google_secret_manager_secret.secrets[*] — 19 resources to add
#           module.secrets.google_secret_manager_secret_iam_member.service_access[*] — N resources to add
```
