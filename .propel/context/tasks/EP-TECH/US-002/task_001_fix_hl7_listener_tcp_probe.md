---
id: TASK-001
title: "Fix hl7-listener Health and Startup Probes to Use TCP Socket on Port 2575"
user_story: US-002
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: []
---

# TASK-001: Fix hl7-listener Health and Startup Probes to Use TCP Socket on Port 2575

> **Story:** US-002 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

`infra/terraform/modules/cloud_run/main.tf` applies a uniform HTTP probe configuration to all 10 services via `for_each = local.services`. Both the `liveness_probe` and `startup_probe` are currently hardcoded to use `http_get path = "/health"` and `http_get path = "/ready"` respectively.

The US-002 technical notes explicitly state:

> *"MLLP listener service (EP-001) does not use HTTP probes — use TCP probe on port 2575"*

The `hl7-listener` service is a raw TCP MLLP server (port 2575). It does not host an HTTP server, so HTTP probes will always fail — causing Cloud Run to restart the container in a crash loop on first deploy. This is a critical configuration defect that must be resolved before any deployment to dev.

---

## Acceptance Criteria Addressed

| US-002 AC | Requirement |
|---|---|
| **Scenario 1** | `When` `gcloud run services describe hl7-listener-dev` is called, probe type must be `tcpSocket` on port `2575`, not `httpGet` |
| **Scenario 3** | Liveness probe must trigger container restart on failure — TCP probe must fire on the correct port or this scenario is unreachable |

---

## Implementation Steps

### 1. Refactor `liveness_probe` to Use `dynamic` Conditional Blocks

In `infra/terraform/modules/cloud_run/main.tf`, replace the static `liveness_probe` block with conditional `dynamic` sub-blocks so that `hl7-listener` receives a TCP probe and all other services retain the HTTP probe.

**Before:**

```hcl
liveness_probe {
  http_get {
    path = "/health"
  }
  period_seconds    = 10
  failure_threshold = 3
}
```

**After:**

```hcl
liveness_probe {
  dynamic "http_get" {
    for_each = each.key != "hl7-listener" ? [1] : []
    content {
      path = "/health"
    }
  }
  dynamic "tcp_socket" {
    for_each = each.key == "hl7-listener" ? [1] : []
    content {
      port = 2575
    }
  }
  period_seconds    = 10
  failure_threshold = 3
}
```

### 2. Refactor `startup_probe` to Use `dynamic` Conditional Blocks

Apply the same conditional pattern to the `startup_probe` block.

**Before:**

```hcl
startup_probe {
  http_get {
    path = "/ready"
  }
  period_seconds    = 5
  failure_threshold = 12 # 60-second startup window
}
```

**After:**

```hcl
startup_probe {
  dynamic "http_get" {
    for_each = each.key != "hl7-listener" ? [1] : []
    content {
      path = "/ready"
    }
  }
  dynamic "tcp_socket" {
    for_each = each.key == "hl7-listener" ? [1] : []
    content {
      port = 2575
    }
  }
  period_seconds    = 5
  failure_threshold = 12 # 60-second startup window
}
```

### 3. Verify No Other MLLP-Only Services Exist

Confirm that `hl7-listener` is the only non-HTTP service in `locals.services`. All remaining 9 services (`api-gateway`, `coordinator-agent`, `docs-agent`, `medrecon-agent`, `bed-mgmt-agent`, `followup-agent`, `comms-agent`, `ml-inference`, `notification-svc`) expose HTTP endpoints and require no change to probe type.

---

## Files Changed

| File | Change |
|---|---|
| `infra/terraform/modules/cloud_run/main.tf` | Replace static `http_get` blocks in `liveness_probe` and `startup_probe` with `dynamic` conditional blocks |

---

## Verification

After applying changes:

```bash
# Verify hl7-listener uses TCP probe
gcloud run services describe hl7-listener-dev \
  --region us-central1 \
  --format "json" | jq '.spec.template.spec.containers[0].livenessProbe'
# Expected: { "tcpSocket": { "port": 2575 }, ... }

# Verify api-gateway retains HTTP probe (regression check)
gcloud run services describe api-gateway-dev \
  --region us-central1 \
  --format "json" | jq '.spec.template.spec.containers[0].livenessProbe'
# Expected: { "httpGet": { "path": "/health" }, ... }
```

---

## Definition of Done Traceability

| DoD Item | Satisfied by This Task |
|---|---|
| All 10 service definitions have `liveness_probe` configured | ✓ — hl7-listener now has a valid TCP liveness probe |
| Services scale reliably under load | ✓ — crash-loop on hl7-listener caused by invalid HTTP probe is eliminated |

---

## Effort Estimation

| Factor | Assessment |
|---|---|
| Complexity | Low — single-file Terraform refactor using standard `dynamic` block pattern |
| Risk | Medium — probe change affects production traffic routing; must be tested in dev first |
| **Estimate** | **2 h** |
