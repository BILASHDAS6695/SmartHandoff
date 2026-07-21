---
id: TASK-003
title: "Verify Multi-Zone Deployment Spread for All Cloud Run Services"
user_story: US-002
epic: EP-TECH
sprint: 1
layer: DevOps / Verification
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Verify Multi-Zone Deployment Spread for All Cloud Run Services

> **Story:** US-002 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** DevOps / Verification | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-002 **Definition of Done** requires:

> *"Multi-zone deployment verified (services spread across ≥2 GCP zones)"*

Cloud Run (fully managed) automatically distributes instances across multiple zones within the configured region. Unlike GKE or Compute Engine, there is no explicit zone affinity or anti-affinity configuration surface in the Terraform `google_cloud_run_v2_service` resource. The platform enforces zone spread transparently.

However, the DoD requires **verified** evidence of multi-zone spread — not assumed. This task produces that evidence by:

1. Confirming the Cloud Run region (`us-central1`) maps to ≥3 available zones.
2. Running a load test in dev to ensure multiple instances are spawned and verifying their zone distribution via Cloud Logging.
3. Adding a note to `modules/cloud_run/README.md` documenting that zone spread is platform-managed (prevents future engineers from adding unnecessary zone pinning).

---

## Acceptance Criteria Addressed

| US-002 AC | Requirement |
|---|---|
| **Scenario 1** | `When` `gcloud run services describe <service>` is called, services must be confirmed as multi-zone capable |
| **DoD** | Multi-zone deployment verified (services spread across ≥2 GCP zones) |

---

## Implementation Steps

### 1. Confirm Region Zone Availability

Run the following to confirm the deployment region supports ≥3 zones (required for meaningful spread):

```bash
gcloud compute zones list \
  --filter="region:us-central1 AND status:UP" \
  --format="value(name)"
# Expected output: us-central1-a, us-central1-b, us-central1-c, us-central1-f
```

If the configured region differs from `us-central1`, substitute accordingly. Record the output as evidence.

### 2. Verify Cloud Run Instance Zone Labels via Cloud Logging

After `terraform apply` on dev, Cloud Run emits structured log entries per instance with `resource.labels.zone`. Query Cloud Logging to confirm zone spread across ≥2 zones:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" \
   resource.labels.service_name="coordinator-agent-dev" \
   logName=~"run.googleapis.com/requests"' \
  --project=<dev-project-id> \
  --limit=50 \
  --format="value(resource.labels.zone)" \
  | sort -u
# Expected: at least 2 distinct zone values (e.g., us-central1-a, us-central1-c)
```

Repeat for `api-gateway-dev` (min_instances=2 — most likely to show multi-zone spread at rest) and `hl7-listener-dev` (min_instances=1 — requires load to trigger second instance).

### 3. Confirm Minimum Instance Counts for Critical Services

Per `locals.services` in `main.tf`, verify the following min-instance values prevent cold-start gaps that would defeat multi-zone evidence gathering:

| Service | `min_instance_count` | Rationale |
|---|---|---|
| `api-gateway` | 2 | Latency-sensitive; two warm instances ensure cross-zone placement at rest |
| `coordinator-agent` | 1 | Critical; single warm instance; second zone only under load |
| `hl7-listener` | 1 | MLLP must always be listening; second zone under load |

### 4. Update `modules/cloud_run/README.md`

Add a **Multi-Zone Deployment** section to document platform-managed zone spread. This prevents engineers from adding unnecessary `cloud_run_v2_service` zone overrides.

```markdown
## Multi-Zone Deployment

Cloud Run (fully managed) automatically distributes instances across multiple
availability zones within the configured region. Zone scheduling is managed by
the Google Cloud platform and cannot be overridden at the service level.

Verified region: `us-central1` (zones: us-central1-a, us-central1-b,
us-central1-c, us-central1-f). Services with `min_instance_count ≥ 2`
(e.g., `api-gateway`) maintain warm instances in ≥2 zones at all times.

**Do not** add `zones` or node affinity annotations to `google_cloud_run_v2_service`
resources — they are not valid fields and will cause `terraform validate` errors.
```

---

## Files Changed

| File | Change |
|---|---|
| `infra/terraform/modules/cloud_run/README.md` | Add **Multi-Zone Deployment** section |

---

## Evidence Required for DoD

Attach the following artefacts to the pull request:

- [ ] Output of `gcloud compute zones list --filter="region:us-central1 AND status:UP"` showing ≥3 active zones
- [ ] Cloud Logging query output showing ≥2 distinct zone values for `api-gateway-dev`
- [ ] Screenshot or log export showing `coordinator-agent-dev` instances in ≥2 zones under synthetic load

---

## Definition of Done Traceability

| DoD Item | Satisfied by This Task |
|---|---|
| Multi-zone deployment verified (services spread across ≥2 GCP zones) | ✓ — evidenced by Cloud Logging zone label output and documented in README |
| 99.9% uptime SLA | ✓ — multi-zone placement ensures no single zone failure takes down all instances |

---

## Effort Estimation

| Factor | Assessment |
|---|---|
| Complexity | Low — primarily verification and documentation; no code changes to main.tf |
| Risk | Low — Cloud Run multi-zone spread is a platform guarantee, not configurable |
| **Estimate** | **2 h** |
