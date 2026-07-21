---
id: TASK-005
title: "Execute terraform validate and terraform plan for cloud_run Module — Dev Environment"
user_story: US-002
epic: EP-TECH
sprint: 1
layer: DevOps / Validation
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-005: Execute `terraform validate` and `terraform plan` for cloud_run Module — Dev Environment

> **Story:** US-002 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** DevOps / Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

TASK-001 and TASK-002 introduce structural changes to `infra/terraform/modules/cloud_run/main.tf`:

- Replacing static `http_get` blocks with conditional `dynamic` sub-blocks in `liveness_probe` and `startup_probe`
- Adding a new `readiness_probe` block with conditional `dynamic` sub-blocks

These changes must be validated before any `terraform apply` is executed in a real GCP environment. The Terraform `dynamic` block pattern with `for_each` conditionals is syntactically stricter than static blocks — a malformed conditional will pass `terraform validate` but fail at plan time with a provider-level schema error.

This task executes the full validation sequence: **fmt → validate → plan → (apply) → plan (idempotency)**.

---

## Acceptance Criteria Addressed

| US-002 AC | Requirement |
|---|---|
| **Scenario 1** | `When` `terraform apply` is executed for the dev environment, `Then` all 10 services are created/updated with zero errors and plan shows no delta on re-run |
| **DoD** | `terraform apply` on dev environment completes with zero errors |

---

## Implementation Steps

### 1. Pre-flight Checks

Before running Terraform commands, verify:

- [ ] `terraform.tfvars` exists at `infra/terraform/environments/dev/` (copied from `terraform.tfvars.example`) with real values:
  - `project_id` — real GCP dev project ID
  - `region` — `us-central1`
  - `environment` — `"dev"`
- [ ] GCP credentials configured: `gcloud auth application-default login`
- [ ] GCS state bucket `smarthandoff-tf-state-dev` exists (`infra/terraform/environments/dev/backend.tf`)
- [ ] Required GCP APIs are enabled (see `infra/BOOTSTRAP.md`)
- [ ] US-001 networking resources are already provisioned — VPC connector ID is available as Terraform output

### 2. Format Check

```bash
cd infra/terraform/environments/dev

terraform fmt -check -recursive ../../modules/cloud_run/
# Must exit 0. If exit 1, run: terraform fmt -recursive ../../modules/cloud_run/
```

### 3. Module Syntax Validation

```bash
terraform validate
# Must exit 0 with: "Success! The configuration is valid."
# A non-zero exit indicates a schema or syntax error in the dynamic probe blocks.
```

**Common failure modes for `dynamic` blocks in probes:**

| Error | Cause | Fix |
|---|---|---|
| `Blocks of type "http_get" are not expected here` | `dynamic "http_get"` used inside block that only allows one unnamed sub-block | Check provider version supports `dynamic` inside probe blocks |
| `An argument named "for_each" is not expected here` | Terraform < 0.13 syntax | Upgrade Terraform version |
| `The argument "port" is required` | `tcp_socket` block missing `port` | Verify `port = 2575` is present |

### 4. Terraform Plan

```bash
terraform plan \
  -var-file="terraform.tfvars" \
  -out=plan_output.tfplan \
  2>&1 | tee plan_output.txt
```

Review `plan_output.txt` for:

- [ ] **No resource destructions** (`-`) on existing Cloud Run services from US-001 apply
- [ ] **10 `google_cloud_run_v2_service` updates** (probe configuration changes from TASK-001 and TASK-002)
- [ ] **Zero errors** at the bottom of the plan output
- [ ] Probe block diffs show `readiness_probe` added and `liveness_probe` / `startup_probe` updated with TCP socket for `hl7-listener`

Expected diff excerpt for `hl7-listener-dev`:

```diff
~ resource "google_cloud_run_v2_service" "services" ["hl7-listener"] {
  ~ template {
    ~ containers {
      ~ liveness_probe {
        - http_get { path = "/health" }
        + tcp_socket { port = 2575 }
      }
      ~ startup_probe {
        - http_get { path = "/ready" }
        + tcp_socket { port = 2575 }
      }
      + readiness_probe {
        + tcp_socket { port = 2575 }
        + period_seconds    = 10
        + failure_threshold = 3
      }
    }
  }
}
```

Expected diff excerpt for `api-gateway-dev` (HTTP probe retained, readiness_probe added):

```diff
~ resource "google_cloud_run_v2_service" "services" ["api-gateway"] {
  ~ template {
    ~ containers {
      + readiness_probe {
        + http_get { path = "/ready" }
        + period_seconds    = 10
        + failure_threshold = 3
      }
    }
  }
}
```

### 5. Terraform Apply

```bash
terraform apply plan_output.tfplan
# Must exit 0. Record apply duration and resource change count.
```

### 6. Idempotency Check

```bash
terraform plan \
  -var-file="terraform.tfvars" \
  -detailed-exitcode
# Exit code 0 = no changes (idempotent). Exit code 2 = changes pending (fail).
```

A non-zero exit code on the idempotency plan is a **blocking defect** — investigate and resolve before TASK-004 validation can proceed.

---

## Files Changed

| File | Change |
|---|---|
| None (validation artefacts only) | — |

Attach `plan_output.txt` and idempotency plan output to the pull request as required evidence.

---

## Evidence Required for DoD

- [ ] `terraform validate` output showing `"Success! The configuration is valid."`
- [ ] `plan_output.txt` showing probe changes for all 10 services and zero errors
- [ ] `terraform apply` exit code `0`
- [ ] Idempotency plan exit code `0` (no changes after apply)

---

## Definition of Done Traceability

| DoD Item | Satisfied by This Task |
|---|---|
| `terraform apply` on dev environment completes with zero errors | ✓ |
| Post-apply `terraform plan` shows no changes (idempotent) | ✓ |

---

## Effort Estimation

| Factor | Assessment |
|---|---|
| Complexity | Medium — `dynamic` block probe configuration has higher schema validation risk than static blocks |
| Risk | Medium — requires live GCP dev project; VPC connector from US-001 must exist |
| **Estimate** | **2 h** |
