---
id: TASK-004
title: "Validate Cloud Run Service Resource Specs and Probe Endpoints in Dev"
user_story: US-002
epic: EP-TECH
sprint: 1
layer: DevOps / Validation
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-004: Validate Cloud Run Service Resource Specs and Probe Endpoints in Dev

> **Story:** US-002 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** DevOps / Validation | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-002 **Acceptance Criteria Scenario 1** requires:

> *"`gcloud run services describe <service>` is called for each of the 10 services, and CPU, memory, min-instances, and max-instances match the values in the Terraform `variables.tf` and no service uses the Cloud Run default."*

US-002 **Definition of Done** requires:

> *"`GET /health` returns `{"status": "ok"}` for all services in the dev environment"*
> *"`GET /ready` returns `{"status": "ready"}` only after startup dependencies (DB, Redis) are reachable"*

This task executes post-`terraform apply` validation for all 10 Cloud Run services in the dev environment. It produces documented evidence that resource specs and probe endpoints match the Terraform configuration exactly — no reliance on Cloud Run defaults.

**Pre-requisite:** `terraform apply` must have completed successfully in the dev environment (covered by TASK-005 which follows this task in the pipeline; however, this task defines the validation steps so they can be executed atomically after apply).

---

## Acceptance Criteria Addressed

| US-002 AC | Requirement |
|---|---|
| **Scenario 1** | CPU, memory, min/max instances match Terraform values for all 10 services |
| **Scenario 2** | Readiness probe blocks traffic when `/ready` returns 503 |
| **Scenario 3** | Liveness probe triggers restart after 3 consecutive `/health` failures |
| **Scenario 4** | VPC connector binding routes Cloud SQL connections through the private path |

---

## Implementation Steps

### 1. Resource Spec Validation (All 10 Services)

Run `gcloud run services describe` for each service and compare CPU, memory, min/max instances against the `locals.services` map in `cloud_run/main.tf`.

Use the following script to automate across all services:

```bash
#!/usr/bin/env bash
# validate_cloud_run_specs.sh
PROJECT_ID="<dev-project-id>"
REGION="us-central1"
ENV="dev"

SERVICES=(
  "api-gateway"
  "hl7-listener"
  "coordinator-agent"
  "docs-agent"
  "medrecon-agent"
  "bed-mgmt-agent"
  "followup-agent"
  "comms-agent"
  "ml-inference"
  "notification-svc"
)

for SVC in "${SERVICES[@]}"; do
  echo "=== ${SVC}-${ENV} ==="
  gcloud run services describe "${SVC}-${ENV}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format="json" | jq '{
      cpu:          .spec.template.spec.containers[0].resources.limits.cpu,
      memory:       .spec.template.spec.containers[0].resources.limits.memory,
      min_instances: .spec.template.metadata.annotations["autoscaling.knative.dev/minScale"],
      max_instances: .spec.template.metadata.annotations["autoscaling.knative.dev/maxScale"],
      concurrency:  .spec.template.spec.containerConcurrency,
      vpc_connector: .spec.template.metadata.annotations["run.googleapis.com/vpc-access-connector"],
      liveness_probe: .spec.template.spec.containers[0].livenessProbe,
      readiness_probe: .spec.template.spec.containers[0].readinessProbe,
      startup_probe: .spec.template.spec.containers[0].startupProbe
    }'
  echo ""
done
```

#### Expected Values per Service

| Service | CPU | Memory | Min | Max | Concurrency |
|---|---|---|---|---|---|
| `api-gateway` | `2000m` | `2Gi` | `2` | `20` | `100` |
| `hl7-listener` | `1000m` | `512Mi` | `1` | `10` | `50` |
| `coordinator-agent` | `2000m` | `2Gi` | `1` | `10` | `20` |
| `docs-agent` | `2000m` | `4Gi` | `1` | `10` | `5` |
| `medrecon-agent` | `2000m` | `2Gi` | `1` | `10` | `10` |
| `bed-mgmt-agent` | `1000m` | `1Gi` | `1` | `5` | `20` |
| `followup-agent` | `1000m` | `1Gi` | `1` | `10` | `20` |
| `comms-agent` | `2000m` | `2Gi` | `1` | `10` | `10` |
| `ml-inference` | `2000m` | `2Gi` | `1` | `5` | `50` |
| `notification-svc` | `1000m` | `512Mi` | `1` | `5` | `50` |

Any mismatch is a **blocking defect** — do not proceed to TASK-005 until all values match.

### 2. Probe Configuration Validation

Verify probe types are correct for each service group:

```bash
# HTTP services — verify liveness probe is httpGet /health
for SVC in api-gateway coordinator-agent docs-agent medrecon-agent \
           bed-mgmt-agent followup-agent comms-agent ml-inference notification-svc; do
  echo "--- ${SVC}-${ENV}: liveness ---"
  gcloud run services describe "${SVC}-${ENV}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --format="json" | jq '.spec.template.spec.containers[0].livenessProbe.httpGet.path'
  # Expected: "/health"
done

# hl7-listener — verify TCP probes
echo "--- hl7-listener-${ENV}: liveness (must be TCP 2575) ---"
gcloud run services describe "hl7-listener-${ENV}" \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format="json" | jq '.spec.template.spec.containers[0].livenessProbe.tcpSocket.port'
# Expected: 2575
```

### 3. Health Endpoint Smoke Test (`GET /health`)

For the 9 HTTP services, obtain the service URL and issue a curl call. Services with `INGRESS_TRAFFIC_INTERNAL_ONLY` must be tested from within the VPC (e.g., via Cloud Shell or a bastion VM connected to the VPC):

```bash
# For public endpoint (api-gateway only):
API_URL=$(gcloud run services describe api-gateway-${ENV} \
  --project="${PROJECT_ID}" --region="${REGION}" --format="value(status.url)")
curl -s "${API_URL}/health" | jq .
# Expected: {"status": "ok"}

# For internal services — run from Cloud Shell (connected to VPC via VPC Connector):
COORDINATOR_URL=$(gcloud run services describe coordinator-agent-${ENV} \
  --project="${PROJECT_ID}" --region="${REGION}" --format="value(status.url)")
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "${COORDINATOR_URL}/health" | jq .
# Expected: {"status": "ok"}
```

Repeat for all 9 HTTP services. Record pass/fail per service.

### 4. Readiness Endpoint Smoke Test (`GET /ready`)

```bash
# Test readiness endpoint returns {"status": "ready"} when deps are healthy
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "${COORDINATOR_URL}/ready" | jq .
# Expected: {"status": "ready"}
```

**Note:** The `/ready` response is application-level logic. If the application placeholder images are still deployed (not the real service images), this endpoint may not be implemented yet. In that case, document the expected contract and flag as pending until real service images are deployed.

### 5. VPC Connector Binding Validation (Scenario 4)

Verify Cloud SQL private IP connectivity routes through the VPC connector:

```bash
# Check VPC connector annotation is present on all non-public services
gcloud run services describe coordinator-agent-${ENV} \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format="json" | jq '.spec.template.metadata.annotations["run.googleapis.com/vpc-access-connector"]'
# Expected: "projects/<project>/locations/<region>/connectors/smarthandoff-connector-dev"

# Verify egress setting
gcloud run services describe coordinator-agent-${ENV} \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format="json" | jq '.spec.template.metadata.annotations["run.googleapis.com/vpc-access-egress"]'
# Expected: "all-traffic"
```

---

## Files Changed

| File | Change |
|---|---|
| None (validation only) | — |

A `validate_cloud_run_specs.sh` script may be committed to `infra/scripts/` for repeatability, but is not required for DoD sign-off.

---

## Evidence Required for DoD

Attach the following artefacts to the pull request:

- [ ] Script output from step 1 showing all 10 services with correct CPU/memory/min/max values
- [ ] Script output from step 2 confirming probe types (HTTP vs TCP) match expected values
- [ ] `curl` output from step 3 showing `{"status": "ok"}` for `api-gateway-dev`
- [ ] VPC connector annotation output from step 5 for at least 3 services

---

## Definition of Done Traceability

| DoD Item | Satisfied by This Task |
|---|---|
| CPU, memory, min/max instances match Terraform values for all 10 services | ✓ |
| `GET /health` returns `{"status": "ok"}` for all services in dev | ✓ |
| `GET /ready` returns `{"status": "ready"}` after startup deps are reachable | ✓ (pending real images) |

---

## Effort Estimation

| Factor | Assessment |
|---|---|
| Complexity | Medium — 10 services × 5 validation dimensions; requires VPC access for internal services |
| Risk | Medium — internal services require VPC-connected test client; placeholder images may not implement `/ready` |
| **Estimate** | **3 h** |
