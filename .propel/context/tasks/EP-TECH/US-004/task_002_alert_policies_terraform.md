---
id: TASK-002
title: "Implement P1/P2/P3 Alert Policies in `monitoring` Terraform Module"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-002: Implement P1/P2/P3 Alert Policies in `monitoring` Terraform Module

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

With notification channels provisioned in TASK-001, this task defines the three `google_monitoring_alert_policy` Terraform resources that map to US-004's DoD:

- **P1** — error rate >1% for 60 s → triggers email + PagerDuty
- **P2** — request latency p95 >5 s for 60 s → triggers email only
- **P3** — DLQ (Dead-Letter Queue) message count >0 for 60 s → triggers email only

Alert policies are expressed as MQL (Monitoring Query Language) conditions to enable precise aggregation windows and percentile calculations. All resources live in `infra/terraform/modules/monitoring/main.tf`, keeping IaC compliance per the US-004 Technical Notes.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 1** | P1 alert fires within 2 minutes when error rate >1% for 60 s; Cloud Monitoring shows active alert |

---

## Implementation Steps

### 1. Add Alert Policy Resources to `monitoring/main.tf`

Append the following three alert policy blocks after the notification channel resources from TASK-001.

#### P1 — Error Rate Alert

```hcl
resource "google_monitoring_alert_policy" "p1_error_rate" {
  project      = var.project_id
  display_name = "[P1] SmartHandoff — Error Rate >1% (${var.environment})"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run request error rate >1% for 60s"

    condition_monitoring_query_language {
      query    = <<-EOT
        fetch cloud_run_revision
        | metric 'run.googleapis.com/request_count'
        | filter (resource.labels.project_id == '${var.project_id}')
        | align rate(60s)
        | group_by [resource.labels.service_name], [
            error_requests: sum(if(metric.labels.response_code_class != '2xx', val(), 0)),
            total_requests: sum(val())
          ]
        | value [error_rate: error_requests / if(total_requests > 0, total_requests, 1)]
        | condition error_rate > 0.01
      EOT
      duration = "60s"
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email.name,
    google_monitoring_notification_channel.pagerduty.name,
  ]

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }

  user_labels = {
    severity    = "p1"
    environment = var.environment
    managed_by  = "terraform"
  }

  documentation {
    content   = "P1 — SmartHandoff error rate exceeds 1% threshold. Investigate Cloud Run logs for the affected service. Runbook: https://wiki.internal/runbooks/smarthandoff-p1-error-rate"
    mime_type = "text/markdown"
  }
}
```

#### P2 — Latency p95 Alert

```hcl
resource "google_monitoring_alert_policy" "p2_latency_p95" {
  project      = var.project_id
  display_name = "[P2] SmartHandoff — Request Latency p95 >5s (${var.environment})"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run request latency p95 >5s for 60s"

    condition_monitoring_query_language {
      query    = <<-EOT
        fetch cloud_run_revision
        | metric 'run.googleapis.com/request_latencies'
        | filter (resource.labels.project_id == '${var.project_id}')
        | align delta(60s)
        | every 60s
        | group_by [resource.labels.service_name],
            [p95_latency: percentile(value.request_latencies, 95)]
        | condition p95_latency > 5000
      EOT
      duration = "60s"
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email.name,
  ]

  alert_strategy {
    notification_rate_limit {
      period = "600s"
    }
    auto_close = "3600s"
  }

  user_labels = {
    severity    = "p2"
    environment = var.environment
    managed_by  = "terraform"
  }

  documentation {
    content   = "P2 — SmartHandoff p95 request latency exceeds 5-second SLA threshold. Check downstream dependency latency (Cloud SQL, Vertex AI, Pub/Sub). Runbook: https://wiki.internal/runbooks/smarthandoff-p2-latency"
    mime_type = "text/markdown"
  }
}
```

#### P3 — DLQ Message Count Alert

```hcl
resource "google_monitoring_alert_policy" "p3_dlq_messages" {
  project      = var.project_id
  display_name = "[P3] SmartHandoff — DLQ Messages >0 (${var.environment})"
  combiner     = "OR"

  conditions {
    display_name = "Pub/Sub DLQ subscription undelivered message count >0 for 60s"

    condition_monitoring_query_language {
      query    = <<-EOT
        fetch pubsub_subscription
        | metric 'pubsub.googleapis.com/subscription/num_undelivered_messages'
        | filter
            resource.labels.project_id == '${var.project_id}'
            && resource.labels.subscription_id =~ 'smarthandoff-.*-dlq.*'
        | group_by [resource.labels.subscription_id], [max_undelivered: max(val())]
        | condition max_undelivered > 0
      EOT
      duration = "60s"
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email.name,
  ]

  alert_strategy {
    notification_rate_limit {
      period = "1800s"
    }
    auto_close = "86400s"
  }

  user_labels = {
    severity    = "p3"
    environment = var.environment
    managed_by  = "terraform"
  }

  documentation {
    content   = "P3 — One or more Pub/Sub dead-letter queues contain unprocessed messages. Inspect DLQ subscription for failed ADT event payloads. Runbook: https://wiki.internal/runbooks/smarthandoff-p3-dlq"
    mime_type = "text/markdown"
  }
}
```

### 2. Export Alert Policy IDs in `monitoring/outputs.tf`

Append to existing outputs from TASK-001:

```hcl
output "p1_error_rate_alert_policy_id" {
  description = "Resource name of the P1 error rate alert policy."
  value       = google_monitoring_alert_policy.p1_error_rate.name
}

output "p2_latency_alert_policy_id" {
  description = "Resource name of the P2 latency p95 alert policy."
  value       = google_monitoring_alert_policy.p2_latency_p95.name
}

output "p3_dlq_alert_policy_id" {
  description = "Resource name of the P3 DLQ alert policy."
  value       = google_monitoring_alert_policy.p3_dlq_messages.name
}
```

---

## Files Changed

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/main.tf` | Append three alert policy resources |
| `infra/terraform/modules/monitoring/outputs.tf` | Append three alert policy ID outputs |

---

## Definition of Done

- [ ] `terraform validate` passes with all three alert policy resources
- [ ] `terraform plan` shows three new `google_monitoring_alert_policy` resources
- [ ] P1 alert references both email and PagerDuty channels
- [ ] P2 and P3 alerts reference email channel only
- [ ] DLQ filter regex matches the `smarthandoff-*-dlq*` subscription naming convention used in the `pubsub` module
- [ ] Documentation runbook URLs are populated before `prod` apply
