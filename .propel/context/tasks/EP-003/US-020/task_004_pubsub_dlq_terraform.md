---
id: TASK-004
title: "Configure Terraform Pub/Sub DLQ Subscription for `coordinator-sub` (max_delivery_attempts=5) and Cloud Monitoring Alert"
user_story: US-020
epic: EP-003
sprint: 2
layer: Infrastructure
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-001/TASK-001]
---

# TASK-004: Configure Terraform Pub/Sub DLQ Subscription for `coordinator-sub` (max_delivery_attempts=5) and Cloud Monitoring Alert

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Infrastructure | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-020 mandates (TR-015, ADR-001):

> *"DLQ receives message after 5 failed deliveries; a Cloud Monitoring alert fires; DLQ message count metric is incremented."*

The existing `infra/terraform/modules/pubsub/` module provisions the `adt-events` topic and per-agent subscriptions. This task extends that module to:

1. Add `coordinator-sub` subscription with `dead_letter_policy { max_delivery_attempts = 5 }`
2. Provision `coordinator-dlq` dead-letter topic and `coordinator-dlq-sub` pull subscription
3. Grant the `pubsub.googleapis.com` service account the `roles/pubsub.publisher` role on the DLQ topic (required by GCP for dead-lettering)
4. Add a Cloud Monitoring alert policy that fires when `coordinator-dlq-sub` backlog exceeds 0 messages

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `max_delivery_attempts = 5` | US-020 SC-4; TR-015 zero-message-loss policy |
| Separate DLQ topic per agent | Independent DLQ management; different alert thresholds per agent |
| Cloud Monitoring alert on backlog > 0 | Operations team is alerted immediately; no silent DLQ accumulation |
| IAM grant in Terraform | Infrastructure-as-code; reproducible across dev/staging/prod |

Design refs: TR-015, ADR-001, US-020 SC-4, DoD.

---

## Acceptance Criteria Addressed

| US-020 AC | Requirement |
|---|---|
| **Scenario 4** | After 5 failed deliveries, message is in `coordinator-dlq-sub`; Cloud Monitoring alert fires; DLQ backlog metric > 0 |

---

## Implementation Steps

### 1. Update `infra/terraform/modules/pubsub/variables.tf` — add coordinator variables

```hcl
variable "coordinator_sub_ack_deadline_seconds" {
  description = "ACK deadline in seconds for the coordinator-sub subscription"
  type        = number
  default     = 60
}

variable "coordinator_dlq_max_delivery_attempts" {
  description = "Number of delivery attempts before a message is sent to coordinator-dlq"
  type        = number
  default     = 5
}

variable "alert_notification_channels" {
  description = "List of Cloud Monitoring notification channel IDs for DLQ alerts"
  type        = list(string)
  default     = []
}
```

### 2. Update `infra/terraform/modules/pubsub/main.tf` — add DLQ topic, subscriptions, IAM, and alert

```hcl
# ---------------------------------------------------------------------------
# coordinator-dlq topic — receives messages after max_delivery_attempts
# ---------------------------------------------------------------------------
resource "google_pubsub_topic" "coordinator_dlq" {
  name    = "coordinator-dlq"
  project = var.project_id

  labels = {
    environment = var.environment
    component   = "coordinator-agent"
    managed_by  = "terraform"
  }
}

# ---------------------------------------------------------------------------
# coordinator-sub — primary subscription with dead-letter policy
# ---------------------------------------------------------------------------
resource "google_pubsub_subscription" "coordinator_sub" {
  name    = "coordinator-sub"
  topic   = google_pubsub_topic.adt_events.id
  project = var.project_id

  ack_deadline_seconds = var.coordinator_sub_ack_deadline_seconds

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.coordinator_dlq.id
    max_delivery_attempts = var.coordinator_dlq_max_delivery_attempts
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  labels = {
    environment = var.environment
    component   = "coordinator-agent"
    managed_by  = "terraform"
  }
}

# ---------------------------------------------------------------------------
# coordinator-dlq-sub — pull subscription for DLQ inspection / replay
# ---------------------------------------------------------------------------
resource "google_pubsub_subscription" "coordinator_dlq_sub" {
  name    = "coordinator-dlq-sub"
  topic   = google_pubsub_topic.coordinator_dlq.id
  project = var.project_id

  ack_deadline_seconds = 600  # Extended for manual review

  labels = {
    environment = var.environment
    component   = "coordinator-agent-dlq"
    managed_by  = "terraform"
  }
}

# ---------------------------------------------------------------------------
# IAM — Pub/Sub service account must publish to DLQ topic
# Required by GCP for dead-letter forwarding to work
# ---------------------------------------------------------------------------
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_pubsub_topic_iam_member" "coordinator_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.coordinator_dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "coordinator_sub_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.coordinator_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# Cloud Monitoring alert — fires when coordinator-dlq-sub backlog > 0
# ---------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "coordinator_dlq_alert" {
  display_name = "Coordinator DLQ — Unprocessed Messages"
  project      = var.project_id
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "coordinator-dlq-sub backlog > 0"

    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"pubsub_subscription\"",
        "resource.labels.subscription_id=\"coordinator-dlq-sub\"",
        "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = var.alert_notification_channels

  documentation {
    content = <<-EOT
      ## Coordinator DLQ Alert

      One or more ADT events have failed processing after ${var.coordinator_dlq_max_delivery_attempts} delivery attempts
      and have been moved to `coordinator-dlq-sub`.

      **Immediate actions:**
      1. Check coordinator-agent Cloud Run logs for the failed `encounter_id`
      2. Inspect the DLQ message: `gcloud pubsub subscriptions pull coordinator-dlq-sub --auto-ack --limit=1`
      3. Identify root cause (DB unavailable, schema mismatch, etc.)
      4. After fix, replay the message to `adt-events` topic

      **Runbook:** https://wiki.internal/smarthandoff/runbooks/coordinator-dlq
    EOT
    mime_type = "text/markdown"
  }

  labels = {
    environment = var.environment
    severity    = "critical"
  }
}
```

### 3. Update `infra/terraform/modules/pubsub/outputs.tf` — expose new resource IDs

```hcl
output "coordinator_sub_id" {
  description = "Full resource ID of the coordinator-sub Pub/Sub subscription"
  value       = google_pubsub_subscription.coordinator_sub.id
}

output "coordinator_dlq_topic_id" {
  description = "Full resource ID of the coordinator-dlq dead-letter topic"
  value       = google_pubsub_topic.coordinator_dlq.id
}

output "coordinator_dlq_sub_id" {
  description = "Full resource ID of the coordinator-dlq-sub pull subscription"
  value       = google_pubsub_subscription.coordinator_dlq_sub.id
}
```

### 4. Update dev/staging/prod environment `main.tf` — pass new variables

In each `infra/terraform/environments/*/main.tf`, update the `pubsub` module call:

```hcl
module "pubsub" {
  source = "../../modules/pubsub"

  # ... existing vars ...

  coordinator_sub_ack_deadline_seconds  = 60
  coordinator_dlq_max_delivery_attempts = 5
  alert_notification_channels           = var.alert_notification_channel_ids
}
```

---

## Validation

Run from `infra/terraform/environments/dev/`:

```bash
# 1. Terraform format check
terraform fmt -check -recursive ../../modules/pubsub/

# 2. Terraform validate (requires GCP credentials)
terraform init -backend=false
terraform validate

# 3. Plan — confirm new resources appear
terraform plan -target=module.pubsub | grep -E "coordinator|dlq|alert"
# Expected output lines:
# + google_pubsub_topic.coordinator_dlq
# + google_pubsub_subscription.coordinator_sub
# + google_pubsub_subscription.coordinator_dlq_sub
# + google_pubsub_topic_iam_member.coordinator_dlq_publisher
# + google_monitoring_alert_policy.coordinator_dlq_alert
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| MODIFY | `infra/terraform/modules/pubsub/main.tf` |
| MODIFY | `infra/terraform/modules/pubsub/variables.tf` |
| MODIFY | `infra/terraform/modules/pubsub/outputs.tf` |
| MODIFY | `infra/terraform/environments/dev/main.tf` |
| MODIFY | `infra/terraform/environments/staging/main.tf` |
| MODIFY | `infra/terraform/environments/prod/main.tf` |

---

## Definition of Done Checklist

- [ ] `coordinator-sub` subscription created with `dead_letter_policy { max_delivery_attempts = 5 }`
- [ ] `coordinator-dlq` dead-letter topic provisioned
- [ ] `coordinator-dlq-sub` pull subscription provisioned on DLQ topic
- [ ] GCP Pub/Sub service account granted `roles/pubsub.publisher` on DLQ topic
- [ ] GCP Pub/Sub service account granted `roles/pubsub.subscriber` on `coordinator-sub`
- [ ] Cloud Monitoring alert fires when `coordinator-dlq-sub` undelivered messages > 0 for 60 s
- [ ] Alert documentation includes runbook link and replay instructions
- [ ] `terraform validate` passes with no errors
- [ ] All 3 environment `main.tf` files updated with new module variables
