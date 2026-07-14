---
task_id: task_002
story_id: us_003
epic: EP-TECH
title: Alert Policy Set — P1/P2/P3 Conditions for All Six Alert Rules
layer: Observability / IaC
effort_hours: 2
sequence: 2
status: Draft
---

# TASK-002: Alert Policy Set — P1/P2/P3 Conditions for All Six Alert Rules

> **Story:** EP-TECH/US-003 | **Layer:** Observability / IaC | **Effort:** 2 hours | **Seq:** 2 of 4

## Objective

Implement all six Terraform-managed alert policies (AC-2 through AC-6): API error rate P1, ADT Pub/Sub lag P1, Cloud SQL replication lag P1, agent task failure rate P2, and DLQ message count P3 — with correct metric filters, thresholds, durations, and notification channel routing.

## Implementation Steps

### 1. Complete Alert Policy Module (`modules/monitoring/alerts.tf`)

```hcl
locals {
  # Notification channels provisioned in Task 003
  p1_channels = [var.email_oncall_channel_id, var.slack_channel_id]
  p2_channels = [var.email_oncall_channel_id]
  p3_channels = [var.slack_channel_id]
}

# ──────────────────────────────────────────────────────────────────────
# P1 ALERT: API Gateway error rate > 1% over 5-minute window (AC-2)
# ──────────────────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "p1_api_error_rate" {
  display_name = "P1: API Error Rate > 1% — ${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  severity     = "CRITICAL"
  enabled      = true

  conditions {
    display_name = "API Gateway 5xx rate exceeds 1% of total requests"

    condition_monitoring_query_language {
      query    = <<-EOT
        fetch cloud_run_revision
        | metric 'run.googleapis.com/request_count'
        | filter (resource.service_name == 'api-gateway-${var.environment}')
        | align rate(5m)
        | every 1m
        | group_by [], [
            total: sum(value.request_count),
            errors: sum(if(metric.response_code_class == '5xx', value.request_count, 0))
          ]
        | value [error_rate: errors / if(total > 0, total, 1)]
        | condition error_rate > 0.01
      EOT
      duration = "300s"  # Must stay above threshold for 5 minutes
    }
  }

  notification_channels = local.p1_channels

  alert_strategy {
    auto_close               = "1800s"  # Auto-close after 30 min if resolved
    notification_rate_limit  { period = "300s" }
  }

  documentation {
    content   = "API Gateway error rate exceeded 1% of requests. Check Cloud Run logs: `gcloud run services logs read api-gateway-${var.environment} --region=us-central1 --project=${var.project_id}`"
    mime_type = "text/markdown"
  }
}

# ──────────────────────────────────────────────────────────────────────
# P1 ALERT: ADT event Pub/Sub processing lag > 10 seconds (AC-3)
# ──────────────────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "p1_adt_pubsub_lag" {
  display_name = "P1: ADT Event Processing Lag > 10s — ${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  severity     = "CRITICAL"
  enabled      = true

  conditions {
    display_name = "coordinator-sub oldest unacked message age > 10 seconds"

    condition_threshold {
      filter = <<-EOT
        resource.type = "pubsub_subscription"
        AND resource.labels.subscription_id = "coordinator-sub-${var.environment}"
        AND metric.type = "pubsub.googleapis.com/subscription/oldest_unacked_message_age"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 10  # seconds
      duration        = "60s"  # Alert after 60 seconds of sustained lag

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = local.p1_channels

  documentation {
    content   = "ADT event processing lag exceeds 10 seconds on coordinator-sub. Check Coordinator Agent logs and Pub/Sub DLQ count. Possible agent crash or overload."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close              = "1800s"
    notification_rate_limit { period = "300s" }
  }
}

# ──────────────────────────────────────────────────────────────────────
# P1 ALERT: Cloud SQL replication lag > 30 seconds (AC-4)
# ──────────────────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "p1_sql_replication_lag" {
  display_name = "P1: Cloud SQL Replica Lag > 30s — ${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  severity     = "CRITICAL"
  enabled      = true

  conditions {
    display_name = "Cloud SQL read replica replication lag exceeds 30 seconds"

    condition_threshold {
      filter = <<-EOT
        resource.type = "cloudsql_database"
        AND resource.labels.database_id = "${var.project_id}:smarthandoff-pg-replica-${var.environment}"
        AND metric.type = "cloudsql.googleapis.com/database/replication/replica_lag"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 30  # seconds
      duration        = "120s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = local.p1_channels

  documentation {
    content   = "Cloud SQL read replica is lagging behind the primary by more than 30 seconds. Dashboard queries may return stale data. Check Cloud SQL instance health in the GCP Console."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close              = "3600s"
    notification_rate_limit { period = "600s" }
  }
}

# ──────────────────────────────────────────────────────────────────────
# P2 ALERT: Agent task failure rate > 5% (AC-5)
# ──────────────────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "p2_agent_failure_rate" {
  display_name = "P2: Agent Task Failure Rate > 5% — ${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  severity     = "ERROR"
  enabled      = true

  # One condition per agent service (excluding api-gateway — covered by P1)
  dynamic "conditions" {
    for_each = toset([
      "coordinator-agent", "docs-agent", "medrecon-agent",
      "bed-mgmt-agent", "followup-agent", "comms-agent",
      "ml-inference", "notification-svc"
    ])

    content {
      display_name = "${conditions.value} 5xx error rate > 5%"

      condition_threshold {
        filter = <<-EOT
          resource.type = "cloud_run_revision"
          AND resource.labels.service_name = "${conditions.value}-${var.environment}"
          AND metric.type = "run.googleapis.com/request_count"
          AND metric.labels.response_code_class = "5xx"
        EOT
        comparison      = "COMPARISON_GT"
        threshold_value = 0.05  # 5% error rate
        duration        = "300s"

        aggregations {
          alignment_period   = "60s"
          per_series_aligner = "ALIGN_RATE"
        }
      }
    }
  }

  notification_channels = local.p2_channels

  documentation {
    content   = "One or more agent services is experiencing >5% error rate. This may impact care transition workflows. Check agent logs and DLQ message counts."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close              = "3600s"
    notification_rate_limit { period = "600s" }
  }
}

# ──────────────────────────────────────────────────────────────────────
# P3 ALERT: Any DLQ subscription message count > 0 (AC-6)
# ──────────────────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "p3_dlq_messages" {
  display_name = "P3: DLQ Message Count > 0 — ${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  severity     = "WARNING"
  enabled      = true

  dynamic "conditions" {
    for_each = toset([
      "adt-events-dlq", "notification-requests-dlq"
    ])

    content {
      display_name = "${conditions.value}-${var.environment} has undelivered messages"

      condition_threshold {
        filter = <<-EOT
          resource.type = "pubsub_subscription"
          AND resource.labels.subscription_id = "${conditions.value}-sub-${var.environment}"
          AND metric.type = "pubsub.googleapis.com/subscription/num_undelivered_messages"
        EOT
        comparison      = "COMPARISON_GT"
        threshold_value = 0
        duration        = "60s"

        aggregations {
          alignment_period   = "60s"
          per_series_aligner = "ALIGN_MAX"
        }
      }
    }
  }

  notification_channels = local.p3_channels

  documentation {
    content   = "Dead Letter Queue contains unprocessed messages. Check which agent is failing and inspect the DLQ messages for error details. Manual intervention may be required."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close              = "86400s"  # Auto-close after 24h
    notification_rate_limit { period = "3600s" }  # Max 1 notification per hour
  }
}
```

### 2. Alert Policy Variables (`modules/monitoring/variables.tf` additions)

```hcl
variable "email_oncall_channel_id" {
  type        = string
  description = "Cloud Monitoring email notification channel ID for P1/P2 alerts"
}

variable "slack_channel_id" {
  type        = string
  description = "Cloud Monitoring Slack notification channel ID for P1/P3 alerts"
}
```

### 3. Outputs for Testing

```hcl
output "alert_policy_ids" {
  value = {
    p1_api_error_rate    = google_monitoring_alert_policy.p1_api_error_rate.name
    p1_adt_pubsub_lag    = google_monitoring_alert_policy.p1_adt_pubsub_lag.name
    p1_sql_replication   = google_monitoring_alert_policy.p1_sql_replication_lag.name
    p2_agent_failures    = google_monitoring_alert_policy.p2_agent_failure_rate.name
    p3_dlq_messages      = google_monitoring_alert_policy.p3_dlq_messages.name
  }
}
```

### 4. Manual Alert Test Procedure

After `terraform apply`, verify each alert fires correctly:

```bash
# Test P1 API error rate — inject 5xx responses for 6 minutes
# Use a Cloud Run env var to enable test error mode

# Test P1 ADT lag — pause coordinator-agent Cloud Run service
gcloud run services update coordinator-agent-dev --no-traffic --region=us-central1
# Wait 2 minutes, verify alert fires, then restore
gcloud run services update coordinator-agent-dev --traffic=100 --region=us-central1

# Test P3 DLQ — publish a message to DLQ directly
gcloud pubsub messages publish adt-events-dlq-dev \
  --message='{"test": "dlq-alert-test"}'
# Verify P3 Slack notification received within 2 minutes
```

## Acceptance Criteria

- [ ] **AC-2:** `gcloud monitoring policies list --project={PROJECT} --filter='displayName:"P1: API Error Rate"'` returns the policy with `severity: CRITICAL`; test injection of 500 responses triggers Slack/email within 5 minutes
- [ ] **AC-3:** Pausing coordinator-agent for 2 minutes triggers the P1 ADT lag alert — confirmed via notification received
- [ ] **AC-4:** Cloud SQL replica lag policy exists with `threshold_value: 30` and `duration: 120s` — confirmed via `gcloud monitoring policies describe {id} --format=json`
- [ ] **AC-5:** P2 agent failure rate policy has 8 conditions (one per non-gateway service) — confirmed via policy JSON
- [ ] **AC-6:** P3 DLQ policy fires within 2 minutes of a test message published directly to `adt-events-dlq-dev` subscription
- [ ] All 5 alert policies are Terraform-managed: `terraform state list | grep monitoring_alert_policy` shows 5 resources; zero policies were created via Cloud Console

## Files to Update

```
infra/terraform/modules/monitoring/alerts.tf    (replace stub with full implementation)
infra/terraform/modules/monitoring/variables.tf (add channel ID variables)
infra/terraform/modules/monitoring/outputs.tf   (add alert_policy_ids output)
```

## Notes

- `condition_monitoring_query_language` (MQL) is used for the error rate P1 because it requires a ratio calculation (errors/total); simple threshold conditions use `condition_threshold` which is easier to configure
- `notification_rate_limit.period = "300s"` prevents alert storm: if error rate oscillates around 1%, only one notification per 5 minutes is sent
- The dynamic `for_each` on the P2 condition creates 8 sub-conditions under one alert policy — this avoids creating 8 separate policies for essentially the same condition type
- `auto_close` ensures resolved alerts don't accumulate as open incidents — important for on-call workflow hygiene
