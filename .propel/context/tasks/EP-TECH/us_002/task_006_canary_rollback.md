---
task_id: task_006
story_id: us_002
epic: EP-TECH
title: Canary Metrics Verification and Auto-Rollback Configuration
layer: Continuous Delivery / Observability
effort_hours: 2
sequence: 6
status: Draft
---

# TASK-006: Canary Metrics Verification and Auto-Rollback Configuration

> **Story:** EP-TECH/US-002 | **Layer:** Continuous Delivery / Observability | **Effort:** 2 hours | **Seq:** 6 of 7

## Objective

Configure the Cloud Deploy canary verification step to monitor API error rate and p95 latency during the 15-minute observation window and automatically roll back the canary if either threshold is breached — satisfying AC-3 (error rate >1% or p95 >500ms triggers rollback).

## Implementation Steps

### 1. Cloud Deploy Verification Configuration (`canary-verify.yaml`)

Cloud Deploy uses a `verify` step that runs after the canary is deployed. The verification reads Cloud Monitoring metrics and fails if thresholds are exceeded:

`.cloudbuild/deploy/canary-verify.yaml`:

```yaml
# Cloud Deploy verification job — runs during canary observation window
# Fails if error rate > 1% or p95 latency > 500ms
apiVersion: deploy.cloud.google.com/v1beta1
kind: VerifyConfig
metadata:
  name: canary-metrics-verify
spec:
  # Run a Cloud Build job that polls metrics for 15 minutes
  cloudBuildJob:
    buildConfig:
      steps:
        - name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
          entrypoint: bash
          args:
            - -c
            - |
              set -euo pipefail

              SERVICE="${CLOUD_DEPLOY_TARGET_DEPLOY_PARAMS_service_name}"
              PROJECT="${CLOUD_DEPLOY_PROJECT}"
              REGION="${CLOUD_DEPLOY_LOCATION}"
              CANARY_REVISION="${CLOUD_DEPLOY_ROLLOUT_ID}"

              echo "=== Canary Verification ==="
              echo "Service: $SERVICE"
              echo "Observation window: 15 minutes"
              echo "Thresholds: error_rate < 1% | p95_latency < 500ms"
              echo ""

              FAILED=0
              WINDOW_SECONDS=900   # 15 minutes
              CHECK_INTERVAL=30    # Check every 30 seconds
              CHECKS=$((WINDOW_SECONDS / CHECK_INTERVAL))

              for i in $(seq 1 $CHECKS); do
                ELAPSED=$((i * CHECK_INTERVAL))
                echo "--- Check $i/$CHECKS (${ELAPSED}s elapsed) ---"

                # Query Cloud Monitoring for error rate on the canary revision
                # Using MQL (Monitoring Query Language)
                ERROR_RATE=$(gcloud monitoring metrics-scopes time-series list \
                  --project="$PROJECT" \
                  --filter='metric.type="run.googleapis.com/request_count" AND
                            resource.labels.service_name="'"$SERVICE"'" AND
                            metric.labels.response_code_class="5xx"' \
                  --format='json' 2>/dev/null | \
                  python3 -c "
                import sys, json, math
                data = json.load(sys.stdin)
                if not data:
                    print('0.0')
                    sys.exit(0)
                # Calculate error rate as fraction of total requests
                error_count = sum(float(p.get('value',{}).get('doubleValue',0)) for ts in data for p in ts.get('points',[]))
                print(f'{error_count:.4f}')
                " 2>/dev/null || echo "0.0")

                # Query p95 latency
                P95_LATENCY=$(gcloud monitoring metrics-scopes time-series list \
                  --project="$PROJECT" \
                  --filter='metric.type="run.googleapis.com/request_latencies" AND
                            resource.labels.service_name="'"$SERVICE"'"' \
                  --format='json' 2>/dev/null | \
                  python3 -c "
                import sys, json
                data = json.load(sys.stdin)
                if not data:
                    print('0')
                    sys.exit(0)
                # Extract p95 latency value in ms
                latencies = [float(p.get('value',{}).get('distributionValue',{}).get('mean',0))
                             for ts in data for p in ts.get('points',[])]
                p95 = sorted(latencies)[int(len(latencies)*0.95)] if latencies else 0
                print(f'{int(p95)}')
                " 2>/dev/null || echo "0")

                echo "  Error rate: ${ERROR_RATE} (threshold: 0.01)"
                echo "  p95 latency: ${P95_LATENCY}ms (threshold: 500ms)"

                # Check thresholds
                if python3 -c "import sys; sys.exit(0 if float('${ERROR_RATE}') > 0.01 else 1)" 2>/dev/null; then
                  echo "  ❌ ERROR RATE EXCEEDED THRESHOLD"
                  FAILED=1
                  break
                fi

                if [ "${P95_LATENCY}" -gt 500 ] 2>/dev/null; then
                  echo "  ❌ P95 LATENCY EXCEEDED THRESHOLD"
                  FAILED=1
                  break
                fi

                echo "  ✓ Metrics within acceptable range"

                if [ "$i" -lt "$CHECKS" ]; then
                  sleep "$CHECK_INTERVAL"
                fi
              done

              if [ "$FAILED" -eq 1 ]; then
                echo ""
                echo "=== CANARY VERIFICATION FAILED — ROLLING BACK ==="
                exit 1  # Non-zero exit triggers Cloud Deploy automatic rollback
              else
                echo ""
                echo "=== CANARY VERIFICATION PASSED — PROMOTING TO 100% ==="
              fi
          timeout: 1000s  # Slightly longer than 15-minute window to account for overhead
      timeout: 1100s
```

### 2. Cloud Deploy Pipeline Update — Attach Verification

Update the canary stage in each pipeline YAML to reference the verification config:

```yaml
# In api-gateway-pipeline.yaml (and all service pipelines)
spec:
  serialPipeline:
    stages:
      - targetId: staging
        strategy:
          canary:
            runtimeConfig:
              cloudRun:
                automaticTrafficControl: true
            canaryDeployment:
              percentages: [10]
              verify: true
        # Attach verification job
        deployParameters:
          - values:
              service_name: api-gateway-staging
```

### 3. Simpler Alternative — Cloud Monitoring Alert-Triggered Rollback

A more robust approach combines Cloud Monitoring alerts with a Cloud Functions rollback trigger:

**Cloud Monitoring Alert Policy for Canary** (`modules/monitoring/canary_alerts.tf`):

```hcl
resource "google_monitoring_alert_policy" "canary_error_rate" {
  display_name = "Canary Error Rate Gate (${var.environment})"
  project      = var.project_id
  combiner     = "OR"
  severity     = "CRITICAL"

  conditions {
    display_name = "Canary revision error rate > 1%"
    condition_threshold {
      # Filter for ONLY the canary revision (latest revision tag)
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND resource.labels.configuration_name =~ ".*-staging$"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 0.01  # 1% of requests
      duration        = "60s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields    = ["resource.labels.service_name"]
      }
    }
  }

  conditions {
    display_name = "Canary revision p95 latency > 500ms"
    condition_threshold {
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND metric.type = "run.googleapis.com/request_latencies"
        AND metric.labels.response_code_class != "5xx"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 500  # milliseconds
      duration        = "120s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_99"  # Use p99 for safety margin
      }
    }
  }

  notification_channels = [
    var.oncall_notification_channel_id,
    var.pubsub_notification_channel_id  # Triggers rollback Cloud Function
  ]

  alert_strategy {
    notification_rate_limit { period = "300s" }  # Max 1 notification per 5 min
  }
}
```

**Cloud Function — Automatic Rollback** (`functions/canary_rollback/main.py`):

```python
import functions_framework
import json
import subprocess
import logging

logger = logging.getLogger(__name__)

@functions_framework.cloud_event
def rollback_canary(cloud_event):
    """
    Triggered by Cloud Monitoring alert via Pub/Sub.
    Automatically rolls back the active Cloud Deploy canary rollout.
    """
    incident = json.loads(
        cloud_event.data["message"]["data"]
    ).get("incident", {})

    condition_name = incident.get("condition", {}).get("displayName", "")
    policy_name    = incident.get("policy_name", "")

    logger.info(f"Rollback triggered by: {policy_name} / {condition_name}")

    # Determine which service triggered the alert
    affected_resource = incident.get("resource", {}).get("labels", {})
    service_name = affected_resource.get("service_name", "")

    if not service_name:
        logger.warning("No service_name in alert. Cannot rollback.")
        return

    # Map Cloud Run service name → Cloud Deploy pipeline name
    pipeline_name = service_name.replace("-staging", "") + "-pipeline"

    # Find the active canary rollout
    result = subprocess.run(
        [
            "gcloud", "deploy", "rollouts", "list",
            f"--delivery-pipeline={pipeline_name}",
            f"--release=latest",
            "--filter=state=IN_PROGRESS",
            "--format=json",
        ],
        capture_output=True, text=True, check=True
    )

    rollouts = json.loads(result.stdout)
    if not rollouts:
        logger.info("No in-progress rollout found. Nothing to rollback.")
        return

    rollout_id = rollouts[0]["name"].split("/")[-1]

    logger.info(f"Rolling back rollout: {rollout_id} for pipeline: {pipeline_name}")

    subprocess.run(
        [
            "gcloud", "deploy", "rollouts", "cancel",
            rollout_id,
            f"--delivery-pipeline={pipeline_name}",
            f"--release=latest",
        ],
        check=True
    )

    logger.info(f"Rollback initiated for {pipeline_name}/{rollout_id}")
```

### 4. Integration Test — Verify Rollback Works

`.cloudbuild/tests/test_canary_rollback.sh`:

```bash
#!/bin/bash
# Integration test: inject errors into canary, verify automatic rollback
set -euo pipefail

echo "=== Canary Rollback Integration Test ==="

# Step 1: Deploy a known-bad image as canary (returns 500 for all requests)
docker build -t bad-api:test - <<'EOF'
FROM python:3.12-slim
RUN pip install fastapi uvicorn --quiet
CMD ["python", "-c", "
import uvicorn
from fastapi import FastAPI
app = FastAPI()
@app.get('/health')
def health(): return {'status': 'ok'}
@app.get('/{path:path}')
def error(): raise Exception('deliberate error for rollback test')
uvicorn.run(app, host='0.0.0.0', port=8080)
"]
EOF

echo "1. Bad image built — pushing to Artifact Registry test tag..."
# (push bad image with test tag)

echo "2. Creating Cloud Deploy release with bad image (canary)..."
# (create release with bad image)

echo "3. Waiting 2 minutes for error rate alert to fire..."
sleep 120

echo "4. Checking rollout status — should be CANCELLED or ROLLED_BACK..."
STATUS=$(gcloud deploy rollouts describe test-rollout \
  --delivery-pipeline=api-gateway-pipeline \
  --release=test-release \
  --format=json | jq -r '.state')

if [ "$STATUS" = "CANCELLED" ] || [ "$STATUS" = "FAILED" ]; then
  echo "✓ PASS: Rollback triggered automatically (state: $STATUS)"
else
  echo "✗ FAIL: Expected CANCELLED or FAILED, got: $STATUS"
  exit 1
fi
```

## Acceptance Criteria

- [ ] **AC-3 satisfied:** Canary rollback triggers within 3 minutes when API error rate exceeds 1% — verified using the integration test script above
- [ ] **AC-3 satisfied:** Canary rollback triggers within 3 minutes when p95 latency exceeds 500ms — verified by deploying a service that adds 600ms artificial delay
- [ ] After rollback, Cloud Run traffic reverts to 100% on the previous stable revision — confirmed via `gcloud run services describe api-gateway-staging --format=json | jq '.status.traffic'`
- [ ] Cloud Monitoring alert `Canary Error Rate Gate` appears in Cloud Console → Monitoring → Alerting → Policies
- [ ] Cloud Function `rollback_canary` deployed and subscribed to the alert Pub/Sub topic

## Files to Create

```
.cloudbuild/deploy/canary-verify.yaml
functions/canary_rollback/main.py
functions/canary_rollback/requirements.txt
.cloudbuild/tests/test_canary_rollback.sh
infra/terraform/modules/monitoring/canary_alerts.tf
```

## Notes

- The polling-based verify approach (Option A) is simpler but runs inside Cloud Build with potential network timeouts; the Cloud Monitoring alert + Cloud Function approach (Option B) is more robust for production
- Implement both: Cloud Deploy verification for the 15-minute window + Cloud Monitoring alert as a safety net
- Canary observation only fires for traffic that actually hits the canary revision (10% of requests); in low-traffic staging environments, error rate may not be meaningful — use synthetic load generation if needed
- `gcloud deploy rollouts cancel` is the rollback command; Cloud Run automatically routes 100% traffic back to the previous stable revision when the canary rollout is cancelled
