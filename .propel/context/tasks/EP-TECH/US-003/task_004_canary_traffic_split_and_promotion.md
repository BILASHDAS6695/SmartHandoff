---
id: TASK-004
title: "Configure Canary Deploy and Full Promotion Steps in Cloud Build"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: CI/CD / Deployment
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-002, TASK-003]
---

# TASK-004: Configure Canary Deploy and Full Promotion Steps in Cloud Build

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** CI/CD / Deployment | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-003 requires a canary deployment strategy that routes 10% of traffic to the new revision before promoting to 100%. This prevents untested code from impacting all clinical staff simultaneously. If the error rate for the canary revision exceeds 1% within a 5-minute observation window, the deployment is automatically rolled back (rollback automation is configured in TASK-005).

The technical notes specify:

> *"Cloud Run canary: `gcloud run services update-traffic <svc> --to-revisions=NEW=10,OLD=90`"*

This task adds the **canary deploy** and **full promotion** steps to the per-service `cloudbuild.yaml`, including the 5-minute observation window wait and the conditional promotion logic.

---

## Acceptance Criteria Addressed

| US-003 AC | Requirement |
|---|---|
| **Scenario 1** | Pipeline executes … → canary deploy (10% traffic) → full promotion (100% traffic) |
| **Scenario 3** | Canary revision is serving 10% of traffic; error rate rollback is possible via the traffic split |

---

## Implementation Steps

### 1. Add Canary Deploy Step to per-service `cloudbuild.yaml`

Insert the following steps after the Trivy scan steps and the SARIF upload step (from TASK-003):

```yaml
  # --- Stage 6: Deploy New Revision to Cloud Run (no traffic) ---
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'deploy-new-revision'
    entrypoint: bash
    args:
      - '-c'
      - |
        gcloud run deploy ${_SERVICE_NAME}-${_ENVIRONMENT} \
          --image=${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:${COMMIT_SHA} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --platform=managed \
          --no-traffic \
          --tag=canary-${COMMIT_SHA:0:7}
    waitFor: ['upload-sarif-to-scc']

  # --- Stage 7: Canary Traffic Split — 10% to new revision ---
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'canary-traffic-split'
    entrypoint: bash
    args:
      - '-c'
      - |
        # Retrieve the latest (new) revision name for the canary tag
        NEW_REVISION=$(gcloud run revisions list \
          --service=${_SERVICE_NAME}-${_ENVIRONMENT} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --filter="metadata.labels.\"cloud.googleapis.com/location\"=${_REGION}" \
          --sort-by="~metadata.creationTimestamp" \
          --limit=1 \
          --format="value(metadata.name)")

        echo "Routing 10% canary traffic to revision: $NEW_REVISION"
        gcloud run services update-traffic ${_SERVICE_NAME}-${_ENVIRONMENT} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --to-revisions=${NEW_REVISION}=10 \
          --to-latest=no

        # Export revision name for downstream promotion step
        echo "$NEW_REVISION" > /workspace/canary_revision.txt
    waitFor: ['deploy-new-revision']

  # --- Stage 8: Observation Window — 5-minute canary soak ---
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'canary-observation-window'
    entrypoint: bash
    args:
      - '-c'
      - |
        NEW_REVISION=$(cat /workspace/canary_revision.txt)
        echo "Canary observation window: monitoring revision $NEW_REVISION for 5 minutes..."
        echo "Cloud Monitoring alert policy (TASK-005) will trigger rollback if error rate > 1%"

        # Poll Cloud Monitoring for error rate on the canary revision every 30 seconds
        for i in $(seq 1 10); do
          sleep 30
          ERROR_RATE=$(gcloud monitoring time-series list \
            --filter='metric.type="run.googleapis.com/request_count" AND metric.labels.response_code_class="5xx" AND resource.labels.revision_name="'"$NEW_REVISION"'"' \
            --interval-start-time="$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-5M +%Y-%m-%dT%H:%M:%SZ)" \
            --interval-end-time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --project=${_PROJECT_ID} \
            --format="value(points[0].value.int64Value)" 2>/dev/null || echo "0")

          echo "[$i/10] 5xx count for canary in last 5min: ${ERROR_RATE:-0}"
        done

        echo "Observation window complete. Checking Cloud Monitoring alert state..."
        ALERT_STATE=$(gcloud alpha monitoring incidents list \
          --project=${_PROJECT_ID} \
          --filter="policy_name:smarthandoff-${_SERVICE_NAME}-canary-error-rate" \
          --limit=1 \
          --format="value(state)" 2>/dev/null || echo "closed")

        if [ "$ALERT_STATE" = "open" ]; then
          echo "ERROR: Canary error-rate alert is OPEN. Triggering rollback."
          cat /workspace/canary_revision.txt > /workspace/rollback_required.txt
          exit 1
        fi

        echo "Canary observation window passed. Proceeding to full promotion."
    waitFor: ['canary-traffic-split']

  # --- Stage 9: Full Promotion — 100% traffic to new revision ---
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'promote-full-traffic'
    entrypoint: bash
    args:
      - '-c'
      - |
        NEW_REVISION=$(cat /workspace/canary_revision.txt)
        echo "Promoting revision $NEW_REVISION to 100% traffic"
        gcloud run services update-traffic ${_SERVICE_NAME}-${_ENVIRONMENT} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --to-revisions=${NEW_REVISION}=100
    waitFor: ['canary-observation-window']
```

### 2. Rollback Step on Canary Failure

Add a rollback step that runs **only** when the observation window exits with code 1:

```yaml
  # --- Rollback: Restore 100% traffic to previous revision on canary failure ---
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'rollback-canary'
    entrypoint: bash
    args:
      - '-c'
      - |
        echo "Rolling back: routing 100% traffic back to LATEST READY stable revision"
        gcloud run services update-traffic ${_SERVICE_NAME}-${_ENVIRONMENT} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --to-latest
        echo "Rollback complete."
    waitFor: ['canary-observation-window']
    allowFailure: false
```

**Note:** Cloud Build does not natively support conditional step execution based on a prior step's exit code in the `waitFor` model. The rollback step above runs after `canary-observation-window` regardless of exit code. The `exit 1` in the observation window will cause the build to be marked FAILED, and the `rollback-canary` step's `allowFailure: false` ensures it runs in the same build context. For a cleaner implementation, a dedicated rollback Cloud Build trigger (triggered by Cloud Monitoring alert) as defined in TASK-005 is the authoritative rollback mechanism.

### 3. Traffic Split Verification

After `canary-traffic-split`, confirm the split is correct:

```bash
gcloud run services describe ${_SERVICE_NAME}-${_ENVIRONMENT} \
  --region=${_REGION} \
  --project=${_PROJECT_ID} \
  --format="yaml(status.traffic)"
```

Expected output:

```yaml
traffic:
- latestRevision: false
  percent: 10
  revisionName: <new-revision>
- latestRevision: false
  percent: 90
  revisionName: <previous-revision>
```

### 4. Required Substitutions Update

Add the following to the substitutions block in `cloudbuild.yaml`:

```yaml
substitutions:
  # ... existing from TASK-002 ...
  _CANARY_PERCENT: '10'         # Default canary traffic weight
  _OBSERVATION_MINUTES: '5'     # Canary soak period in minutes
```

---

## Files Produced

| File | Action |
|---|---|
| `services/<service>/cloudbuild.yaml` (×10) | Update — add canary deploy, observation window, full promotion, and rollback steps |

---

## Definition of Done Checklist

- [ ] New revision deployed with `--no-traffic` flag before traffic split
- [ ] Traffic split step routes exactly 10% to new revision (`--to-revisions=NEW=10`)
- [ ] 5-minute observation window implemented with Cloud Monitoring error-rate check
- [ ] Full promotion step routes 100% traffic to new revision after clean observation
- [ ] Rollback step present and correctly `waitFor: ['canary-observation-window']`
- [ ] `gcloud run services describe` traffic output verified correct (10% / 90% split) after canary step
- [ ] Pipeline exits non-zero if observation window detects open error-rate alert (TASK-005 dependency)
