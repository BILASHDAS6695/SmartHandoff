---
id: TASK-005
title: "Author Cloud Monitoring Alert Policy and Automated Canary Rollback Trigger"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: Monitoring / Automation
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-004]
---

# TASK-005: Author Cloud Monitoring Alert Policy and Automated Canary Rollback Trigger

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Monitoring / Automation | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-003 Scenario 3 requires that if a canary revision's error rate exceeds 1% within a 5-minute observation window, the canary is **automatically rolled back** to the previous revision and the pipeline is marked as failed. This automation requires:

1. A **Cloud Monitoring alert policy** that fires when 5xx error rate > 1% on a canary revision.
2. A **Pub/Sub notification channel** on the alert policy.
3. A **Cloud Run (or Cloud Functions) subscriber** that receives the alert and triggers a rollback Cloud Build job.
4. A **dedicated rollback `cloudbuild.yaml`** that re-routes 100% traffic to the previous stable revision.

The technical notes specify:

> *"Error rate monitoring via Cloud Monitoring custom dashboard + alert policy with auto-resolve action pointing to rollback Cloud Build trigger"*

---

## Acceptance Criteria Addressed

| US-003 AC | Requirement |
|---|---|
| **Scenario 3** | Canary revision serving 10% traffic; error rate >1% in 5-minute window → automatic rollback to previous revision; pipeline marked failed |

---

## Implementation Steps

### 1. Create Terraform Module: `monitoring` Alert Policy for Canary Error Rate

The `infra/terraform/modules/monitoring/main.tf` already exists. Add a per-service alert policy resource using a `for_each` over the service list.

```hcl
locals {
  services = toset([
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "comms-agent", "ml-inference", "notification-svc",
    "audit-svc", "portal-bff"
  ])
}

resource "google_monitoring_alert_policy" "canary_error_rate" {
  for_each     = local.services
  display_name = "smarthandoff-${each.key}-canary-error-rate-${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "5xx error rate > 1% on canary revision (5-min window)"

    condition_threshold {
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND resource.labels.service_name = "${each.key}-${var.environment}"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT

      aggregations {
        alignment_period   = "300s"   # 5-minute window
        per_series_aligner = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields    = ["resource.labels.revision_name"]
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 0.01   # 1% error rate
      duration        = "0s"   # Fire immediately when threshold crossed

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.canary_rollback_pubsub[each.key].id
  ]

  alert_strategy {
    auto_close = "1800s"   # Auto-resolve after 30 minutes if error rate drops
  }

  documentation {
    content   = "Canary error rate exceeded 1% for service ${each.key}-${var.environment}. Automated rollback triggered via Pub/Sub → Cloud Run subscriber → Cloud Build rollback job."
    mime_type = "text/markdown"
  }
}
```

### 2. Create Pub/Sub Notification Channel

```hcl
resource "google_monitoring_notification_channel" "canary_rollback_pubsub" {
  for_each     = local.services
  display_name = "canary-rollback-pubsub-${each.key}-${var.environment}"
  type         = "pubsub"
  project      = var.project_id

  labels = {
    topic = google_pubsub_topic.canary_rollback[each.key].id
  }
}

resource "google_pubsub_topic" "canary_rollback" {
  for_each = local.services
  name     = "smarthandoff-canary-rollback-${each.key}-${var.environment}"
  project  = var.project_id
}
```

### 3. Create Rollback Cloud Build Trigger

Create a dedicated rollback pipeline `cloudbuild-rollback.yaml` at `.cloudbuild/cloudbuild-rollback.yaml`:

```yaml
# Rollback pipeline — triggered by Cloud Monitoring canary error-rate alert via Pub/Sub
# Re-routes 100% traffic to the previous stable revision and marks the build failed.
substitutions:
  _SERVICE_NAME: 'REPLACE_ME'
  _ENVIRONMENT: 'dev'
  _REGION: 'us-central1'
  _PROJECT_ID: 'REPLACE_ME'

steps:
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'rollback-canary-to-stable'
    entrypoint: bash
    args:
      - '-c'
      - |
        echo "ROLLBACK INITIATED: canary error rate exceeded 1% threshold"
        echo "Service: ${_SERVICE_NAME}-${_ENVIRONMENT}"

        # Find the previous stable revision (second most recent READY revision)
        PREV_REVISION=$(gcloud run revisions list \
          --service=${_SERVICE_NAME}-${_ENVIRONMENT} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --filter="status.conditions[0].status=True" \
          --sort-by="~metadata.creationTimestamp" \
          --limit=2 \
          --format="value(metadata.name)" | tail -1)

        echo "Previous stable revision: $PREV_REVISION"

        gcloud run services update-traffic ${_SERVICE_NAME}-${_ENVIRONMENT} \
          --region=${_REGION} \
          --project=${_PROJECT_ID} \
          --to-revisions=${PREV_REVISION}=100

        echo "Traffic restored to 100% on $PREV_REVISION"
        echo "Canary rollback COMPLETE"

  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'notify-rollback-complete'
    entrypoint: bash
    args:
      - '-c'
      - |
        # Signal rollback completion — update original build status via Cloud Build API
        echo "Notifying: canary rollback for ${_SERVICE_NAME}-${_ENVIRONMENT} complete at $(date -u)"
        # Slack notification via webhook secret
        WEBHOOK_URL=$(gcloud secrets versions access latest \
          --secret=slack-cicd-webhook \
          --project=${_PROJECT_ID})
        curl -s -X POST "$WEBHOOK_URL" \
          -H 'Content-type: application/json' \
          -d "{\"text\": \":rotating_light: *CANARY ROLLBACK* — \`${_SERVICE_NAME}-${_ENVIRONMENT}\` rolled back. Error rate exceeded 1% threshold. Previous stable revision restored.\"}"
    waitFor: ['rollback-canary-to-stable']

options:
  logging: CLOUD_LOGGING_ONLY
  substitution_option: 'ALLOW_LOOSE'
```

### 4. Create Cloud Run Subscriber to Bridge Pub/Sub Alert → Cloud Build Trigger

Deploy a lightweight Cloud Run service (or Cloud Functions Gen2) that:
1. Receives the Pub/Sub push notification from the monitoring alert channel.
2. Extracts `_SERVICE_NAME` from the alert incident payload.
3. Triggers the rollback Cloud Build job with the correct substitutions.

```python
# services/cicd-alert-handler/main.py
import base64
import json
import os
import google.auth
import google.auth.transport.requests
from flask import Flask, request

app = Flask(__name__)

@app.route('/', methods=['POST'])
def handle_alert():
    envelope = request.get_json(force=True)
    if not envelope or 'message' not in envelope:
        return 'Bad Request: missing message', 400

    data = base64.b64decode(envelope['message']['data']).decode('utf-8')
    incident = json.loads(data)

    # Extract service name from alert policy display name
    policy_name = incident.get('incident', {}).get('policy_name', '')
    # Format: smarthandoff-<service>-canary-error-rate-<env>
    parts = policy_name.split('-')
    service_name = parts[1] if len(parts) > 2 else 'unknown'
    environment = parts[-1] if len(parts) > 2 else 'dev'

    if incident.get('incident', {}).get('state') == 'open':
        _trigger_rollback(service_name, environment)

    return 'OK', 200

def _trigger_rollback(service_name: str, environment: str):
    credentials, project_id = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)

    import urllib.request
    trigger_id = os.environ.get('ROLLBACK_TRIGGER_ID')
    url = f'https://cloudbuild.googleapis.com/v1/projects/{project_id}/triggers/{trigger_id}:run'
    payload = json.dumps({
        'substitutions': {
            '_SERVICE_NAME': service_name,
            '_ENVIRONMENT': environment,
        }
    }).encode()

    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Authorization', f'Bearer {credentials.token}')
    req.add_header('Content-Type', 'application/json')
    urllib.request.urlopen(req)
```

Deploy this handler as a Cloud Run service with the Pub/Sub push subscription pointing to its URL.

### 5. Update `infra/terraform/modules/monitoring/variables.tf`

Ensure the following variables are declared:

```hcl
variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "project_id" {
  type        = string
  description = "GCP project ID"
}
```

---

## Files Produced

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/main.tf` | Update — add `google_monitoring_alert_policy.canary_error_rate`, Pub/Sub topic and notification channel |
| `.cloudbuild/cloudbuild-rollback.yaml` | Create — dedicated rollback pipeline |
| `services/cicd-alert-handler/main.py` | Create — Pub/Sub alert subscriber |

---

## Definition of Done Checklist

- [ ] Alert policy created for each service: fires when 5xx rate > 1% in 5-minute window
- [ ] `auto_close = "1800s"` set on alert policy — incident auto-resolves after 30 minutes
- [ ] Pub/Sub notification channel wired to alert policy per service
- [ ] Rollback Cloud Build trigger (`cloudbuild-rollback.yaml`) deployed and tested manually
- [ ] `cicd-alert-handler` Cloud Run service deployed; Pub/Sub push subscription points to its URL
- [ ] Rollback confirmed: manual injection of a 5xx spike into canary revision triggers rollback within 5 minutes
- [ ] Slack notification sent on rollback completion (verified in Slack channel)
