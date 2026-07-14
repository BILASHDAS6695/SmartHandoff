---
id: TASK-007
title: "Verify Staging and Production Environments Match Dev Module Structure"
user_story: US-001
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-003]
---

# TASK-007: Verify Staging and Production Environments Match Dev Module Structure

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

The US-001 Technical Notes specify:

> *"Use `terraform workspaces` or environment-specific directories (`environments/dev`, `environments/staging`, `environments/prod`)"*

The DoD requires `terraform apply` to succeed; by implication this applies to all three environments, not just dev. Staging and production environments must mirror the dev module structure to prevent configuration drift that could cause silent failures.

**Current gap analysis** (from code inspection):

| Module block | dev | staging | prod |
|---|---|---|---|
| `module "networking"` | ✅ | ✅ | ✅ |
| `module "cloud_run"` | ✅ | ✅ | ✅ |
| `module "pubsub"` | ✅ | ✅ | ✅ |
| `module "cloud_sql"` | ✅ | ✅ | ✅ |
| `module "storage"` | ✅ | ✅ | ✅ |
| `module "redis"` | ✅ | ✅ | ✅ |
| `module "armor_lb_cdn"` | ✅ | ✅ | ✅ |
| `module "secrets"` | ❌ (TASK-003) | ❌ (TASK-003) | ❌ (TASK-003) |
| `google_project_service.apis` | ✅ | need verify | need verify |

This task verifies staging and prod are consistent **after TASK-003 adds the secrets block** and confirms `apis.tf` and `variables.tf` are also present and consistent.

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 1** | Clean-slate provisioning works for the dev environment (and by extension the parity requirement ensures staging/prod will not diverge) |

---

## Implementation Steps

### 1. Diff `environments/dev/main.tf` vs `environments/staging/main.tf` vs `environments/prod/main.tf`

```bash
# Compare dev vs staging module structure
diff <(grep -E "^module|^  source|^  depends_on" infra/terraform/environments/dev/main.tf) \
     <(grep -E "^module|^  source|^  depends_on" infra/terraform/environments/staging/main.tf)

# Compare dev vs prod module structure
diff <(grep -E "^module|^  source|^  depends_on" infra/terraform/environments/dev/main.tf) \
     <(grep -E "^module|^  source|^  depends_on" infra/terraform/environments/prod/main.tf)
```

**Expected output:** Zero diff after TASK-003 adds the `module "secrets"` block to all three environments.

### 2. Verify `apis.tf` Exists and Is Identical in All Three Environments

```bash
diff infra/terraform/environments/dev/apis.tf \
     infra/terraform/environments/staging/apis.tf

diff infra/terraform/environments/dev/apis.tf \
     infra/terraform/environments/prod/apis.tf
```

**Expected output:** Zero diff. All three environments must enable the same set of GCP APIs. If any environment is missing an API, add it.

### 3. Verify `variables.tf` Has Identical Variable Declarations

```bash
diff infra/terraform/environments/dev/variables.tf \
     infra/terraform/environments/staging/variables.tf

diff infra/terraform/environments/dev/variables.tf \
     infra/terraform/environments/prod/variables.tf
```

**Expected output:** Zero diff. Variable declarations (name, type, description, validation) must be identical across environments. Default values may differ if appropriate (e.g., region).

### 4. Verify `terraform.tfvars.example` Is Complete for All Environments

Check that all variables declared in `variables.tf` have corresponding entries in each environment's `terraform.tfvars.example`:

```bash
for env in dev staging prod; do
  echo "=== $env ==="
  grep "^variable" infra/terraform/environments/$env/variables.tf | \
    sed 's/variable "\(.*\)".*/\1/' | \
  while read var; do
    grep -q "^$var\s*=" infra/terraform/environments/$env/terraform.tfvars.example || \
      echo "MISSING: $var in $env"
  done
done
```

**Expected output:** No `MISSING:` lines. If any variable is missing from an example file, add it with a `<PLACEHOLDER>` value.

### 5. Verify `backend.tf` Specifies Separate State Buckets Per Environment

| Environment | Expected GCS bucket |
|---|---|
| dev | `smarthandoff-tf-state-dev` |
| staging | `smarthandoff-tf-state-staging` |
| prod | `smarthandoff-tf-state-prod` |

```bash
for env in dev staging prod; do
  echo "=== $env backend ==="
  grep "bucket" infra/terraform/environments/$env/backend.tf
done
```

**Expected output:** Each environment references a different, environment-specific bucket.

### 6. Run `terraform validate` for Staging and Prod

```bash
# Staging
cd infra/terraform/environments/staging
terraform init -backend=false
terraform validate

# Prod
cd infra/terraform/environments/prod
terraform init -backend=false
terraform validate
```

Both must return `Success! The configuration is valid.` (`-backend=false` skips GCS bucket existence check for dry-run validation).

---

## Definition of Done

- [ ] `main.tf` module structure is identical across dev, staging, and prod (diff = 0 after TASK-003)
- [ ] `apis.tf` is identical across all three environments
- [ ] `variables.tf` declarations are identical across all three environments
- [ ] `terraform.tfvars.example` contains entries for all declared variables in each environment
- [ ] All three `backend.tf` files reference separate, environment-specific GCS state buckets
- [ ] `terraform validate` passes for staging and prod environments

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-003 | Preceding task | `module "secrets"` must be added to all envs before this diff check |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/environments/staging/apis.tf` | Fix if missing APIs vs dev |
| `infra/terraform/environments/prod/apis.tf` | Fix if missing APIs vs dev |
| `infra/terraform/environments/staging/terraform.tfvars.example` | Add missing variable entries if found |
| `infra/terraform/environments/prod/terraform.tfvars.example` | Add missing variable entries if found |
