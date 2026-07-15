---
id: TASK-005
title: "Execute `terraform validate` and `terraform plan` for Dev Environment — Verify Zero Errors and Idempotency"
user_story: US-001
epic: EP-TECH
sprint: 1
layer: DevOps / Validation
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-005: Execute `terraform validate` and `terraform plan` for Dev Environment — Verify Zero Errors and Idempotency

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** DevOps / Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

This task validates the entire IaC stack for the dev environment before any `terraform apply` is run in a real GCP project. It satisfies the DoD items:

> *"`terraform apply` on dev environment completes with zero errors"*
> *"`terraform plan` post-apply shows no changes (idempotent)"*

The full validation sequence is: **format → validate → plan → apply → plan (idempotency check)**.

Pre-requisite: A real GCP dev project must be available, or a dry-run validation can be performed using `terraform plan -target` and mocked credentials for module syntax checks.

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 1** | `When` `terraform apply` is executed, `Then` all resources created with zero manual console steps and `terraform plan` shows no delta immediately after |

---

## Implementation Steps

### 1. Pre-flight Checks

Before running Terraform commands, verify:

- [ ] `terraform.tfvars` exists for the dev environment (from `terraform.tfvars.example`) with real values:
  - `project_id` — real GCP dev project ID
  - `region` — target region (e.g., `us-central1`)
  - `environment` = `"dev"`
  - `api_domain`, `portal_domain` — dev FQDNs
  - `oncall_email`, `slack_alert_channel` — notification targets
  - `github_owner`, `github_repo` — CI/CD variables
- [ ] GCP credentials configured (`gcloud auth application-default login` or service account key)
- [ ] GCS state bucket `smarthandoff-tf-state-dev` exists (per `backend.tf`) — create manually if not present
- [ ] Required GCP APIs pre-enabled via bootstrap (see `infra/BOOTSTRAP.md`)

### 2. Format Check

```bash
cd infra/terraform/environments/dev
terraform fmt -check -recursive ../../
```

Fix any formatting issues with `terraform fmt -recursive ../../`. No Terraform file should have formatting deviations.

### 3. Module Validation

```bash
# Validate each module individually first
for module in networking cloud_run cloud_sql pubsub redis storage secrets armor_lb_cdn; do
  echo "Validating module: $module"
  cd ../../modules/$module
  terraform init -backend=false
  terraform validate
  cd -
done
```

All modules must return `Success! The configuration is valid.`

### 4. Environment Root Validation

```bash
cd infra/terraform/environments/dev
terraform init
terraform validate
```

Expected output: `Success! The configuration is valid.`

### 5. Plan Execution

```bash
terraform plan -out=tfplan.dev -var-file=terraform.tfvars 2>&1 | tee plan_output.txt
```

Review the plan output for:
- Expected resource counts across all 8 modules (see expected counts below)
- No `destroy` operations on first apply (clean project)
- No `null_resource` workarounds or `local-exec` provisioners (violates IaC policy)
- All module dependencies resolved correctly

**Expected resource count ranges (approximate, may vary by environment):**

| Module | Approximate Resource Count |
|---|---|
| networking | ~8 (VPC, 2 subnets, connector, firewall rules, peering) |
| cloud_run | ~35 (10 services × ~2 + SAs, IAM bindings) |
| cloud_sql | ~12 (primary, replica, KMS, DB, user, secret, scheduler) |
| pubsub | ~15 (topics, subscriptions, DLQ, IAM) |
| redis | ~2 (instance, maintenance policy) |
| storage | ~8 (buckets, KMS, IAM) |
| secrets | ~25 (7 secrets × 2 versions + IAM bindings) |
| armor_lb_cdn | ~12 (WAF policy, LB, CDN, TLS policy, forwarding rules) |
| **Total** | **~120 resources** |

### 6. Apply and Idempotency Verification

```bash
# Apply the plan
terraform apply tfplan.dev

# Immediately run plan again — must show no changes
terraform plan -detailed-exitcode -var-file=terraform.tfvars
```

`-detailed-exitcode` returns exit code `0` for no changes. Any exit code `2` (changes detected) is a failure that must be investigated and resolved.

### 7. Smoke Tests Post-Apply

After apply, run the following CLI checks:

```bash
# Verify Cloud Run services deployed
gcloud run services list --region=us-central1 --project=<project_id>
# Expected: 10 services listed

# Verify Cloud SQL HA
gcloud sql instances describe smarthandoff-pg-dev --project=<project_id> \
  --format="value(settings.availabilityType)"
# Expected: REGIONAL

# Verify VPC Connector
gcloud compute networks vpc-access connectors list --region=us-central1
# Expected: smarthandoff-connector-dev listed

# Verify Secret Manager secrets created
gcloud secrets list --project=<project_id> --filter="name:smarthandoff-"
# Expected: 8+ secrets (7 from secrets module + db-password from cloud_sql)
```

---

## Definition of Done

- [ ] `terraform fmt -check` passes with zero formatting issues
- [ ] `terraform validate` passes for all 8 modules individually
- [ ] `terraform validate` passes for `environments/dev` root
- [ ] `terraform plan` produces a plan with expected resource counts and zero `destroy` operations
- [ ] `terraform apply` completes with exit code `0` and zero errors
- [ ] Post-apply `terraform plan` returns exit code `0` (no changes — idempotent)
- [ ] All 10 Cloud Run services visible in GCP console / `gcloud run services list`
- [ ] Cloud SQL instance shows `REGIONAL` availability type
- [ ] 8+ secrets visible in Secret Manager
- [ ] Plan output archived as `plan_output.txt` in PR for review

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Preceding task | `secrets` module must be implemented |
| TASK-002 | Preceding task | Cloud Run secret mounts must be in place |
| TASK-003 | Preceding task | `secrets` module must be wired into dev root |
| TASK-004 | Preceding task | Cloud SQL scheduler jobs must be added |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/environments/dev/terraform.tfvars` | Create from example — **not committed to source control (add to .gitignore)** |
| `plan_output.txt` | Generated artifact — attach to PR, do not commit |
