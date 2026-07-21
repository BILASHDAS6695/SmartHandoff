---
id: TASK-002
title: "Add readiness_probe to All Cloud Run Services"
user_story: US-002
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

# TASK-002: Add readiness_probe to All Cloud Run Services

> **Story:** US-002 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

`infra/terraform/modules/cloud_run/main.tf` currently configures two probes per container:

- `liveness_probe` — triggers container restart when the application deadlocks (`GET /health`, failure_threshold=3)
- `startup_probe` — blocks traffic during cold start (`GET /ready`, failure_threshold=12 = 60 s window)

The US-002 **Definition of Done** explicitly requires:

> *"All 10 service definitions have `liveness_probe` and `readiness_probe` configured"*

`startup_probe` is a one-shot mechanism that fires only during container initialisation. It does not continuously check readiness after startup completes. A separate `readiness_probe` is needed to shed traffic from a running instance that has lost access to its upstream dependencies (e.g., DB connection pool exhausted, Redis timeout) without triggering a container restart. This is the ongoing readiness gate distinct from the startup gate.

This task adds `readiness_probe` to all 10 service containers, using the same `dynamic` conditional block pattern established in TASK-001 so that `hl7-listener` receives a TCP socket probe and the remaining 9 services receive an HTTP probe.

---

## Acceptance Criteria Addressed

| US-002 AC | Requirement |
|---|---|
| **Scenario 2** | `Given` a new revision is deploying, `When` `GET /ready` returns 503, `Then` traffic is not routed to that revision until it returns 200 |
| **DoD** | All 10 service definitions have `liveness_probe` **and** `readiness_probe` configured |

---

## Implementation Steps

### 1. Add `readiness_probe` Block After `startup_probe` in `cloud_run/main.tf`

Append the following block inside `containers { }`, directly after the closing brace of `startup_probe`:

```hcl
readiness_probe {
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
  period_seconds    = 10
  failure_threshold = 3
  # initial_delay_seconds is intentionally omitted — startup_probe already
  # covers the startup window; readiness_probe fires post-startup only.
}
```

### 2. Verify Probe Ordering in the Container Block

After the edit, the container probe block order must be:

1. `liveness_probe` (modified in TASK-001 to use dynamic blocks)
2. `startup_probe` (modified in TASK-001 to use dynamic blocks)
3. `readiness_probe` (added in this task)

This ordering matches Google Cloud Run v2 provider documentation and avoids `terraform validate` errors from duplicate probe type declarations.

### 3. Confirm LangChain Agent Services Use `startup_probe` for Slow Initialisation

Per the US-002 technical notes:

> *"`startup_probe` recommended for services with slow framework initialisation (LangChain agents)"*

The existing `startup_probe` (failure_threshold=12, period=5s → 60-second window) already accommodates slow LangChain agent initialisation. No change is needed for these services. Verify the following services are covered by the existing startup window:

| Service | Rationale for slow start |
|---|---|
| `docs-agent` | LangChain agent + 4Gi memory |
| `medrecon-agent` | LangChain agent + model loading |
| `coordinator-agent` | LangChain orchestrator + dependency checks |
| `ml-inference` | Model loading from GCS |

---

## Files Changed

| File | Change |
|---|---|
| `infra/terraform/modules/cloud_run/main.tf` | Add `readiness_probe` block with conditional dynamic sub-blocks after `startup_probe` |

---

## Verification

After applying changes, for each of the 10 services:

```bash
# Verify readiness probe is present on an HTTP service
gcloud run services describe api-gateway-dev \
  --region us-central1 \
  --format "json" | jq '.spec.template.spec.containers[0].readinessProbe'
# Expected: { "httpGet": { "path": "/ready" }, "periodSeconds": 10, "failureThreshold": 3 }

# Verify readiness probe is TCP for hl7-listener
gcloud run services describe hl7-listener-dev \
  --region us-central1 \
  --format "json" | jq '.spec.template.spec.containers[0].readinessProbe'
# Expected: { "tcpSocket": { "port": 2575 }, "periodSeconds": 10, "failureThreshold": 3 }
```

Smoke-test readiness shedding on a dev revision by temporarily returning HTTP 503 from `/ready` — confirm Cloud Run routes zero traffic to that revision while `/health` is still 200 (no restart should occur).

---

## Definition of Done Traceability

| DoD Item | Satisfied by This Task |
|---|---|
| All 10 service definitions have `liveness_probe` **and** `readiness_probe` configured | ✓ |
| Services scale reliably under load | ✓ — dependency-saturated instances shed traffic without restart loops |

---

## Effort Estimation

| Factor | Assessment |
|---|---|
| Complexity | Low — additive Terraform block following the same pattern as TASK-001 |
| Risk | Low — `readiness_probe` is additive; no existing probe is removed |
| **Estimate** | **2 h** |
