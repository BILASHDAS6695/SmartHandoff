---
task_id: task_009
story_id: us_001
epic: EP-TECH
title: Cloud Monitoring — Dashboards, Alert Policies, Uptime Checks, and OpenTelemetry
layer: Observability
effort_hours: 2
sequence: 9
status: Draft
---

# TASK-009: Cloud Monitoring — Dashboards, Alert Policies, Uptime Checks, and OpenTelemetry

> **Story:** EP-TECH/US-001 | **Layer:** Observability | **Effort:** 2 hours | **Seq:** 9 of 11

## Objective

Configure Cloud Monitoring with: a service health dashboard for all 10 Cloud Run services, P1/P2/P3 alert policies matching Design §10.1, an uptime check on the API Gateway `/health` endpoint, and an OpenTelemetry-compatible Cloud Trace configuration for distributed tracing across agent chains.

## Implementation Steps

### 1. Notification Channel (Email/Slack for alerts) (`modules/monitoring/main.tf`)

```hcl
resource "google_monitoring_notification_channel" "email_oncall" {
  display_name = "SmartHandoff On-Call Email (${var.environment})"
  type         = "email"
  project      = var.project_id

  labels = {
    email_address = var.oncall_email
  }
}
```

### 2. Uptime Check — API Gateway `/health`

```hcl
resource "google_monitoring_uptime_check_config" "api_health" {
  display_name = "API Gateway Health (${var.environment})"
  project      = var.project_id
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.api_domain
    }
  }

  content_matchers {
    content = "\"status\": \"ok\""
    matcher = "CONTAINS_STRING"
  }
}
```

### 3. Alert Policies

```hcl
locals {
  alert_policies = {
    # P1: API error rate > 1% over 5 minutes
    "p1-api-error-rate" = {
      display_name = "P1: API Error Rate > 1% (${var.environment})"
      severity     = "CRITICAL"
      filter       = <<-EOT
        resource.type = "cloud_run_revision"
        AND resource.labels.service_name = "api-gateway-${var.environment}"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT
      threshold_value = 0.01  # 1% of requests
      comparison      = "COMPARISON_GT"
      duration        = "300s"  # 5-minute window
    }

    # P1: ADT event processing lag > 10 seconds
    "p1-adt-processing-lag" = {
      display_name = "P1: ADT Event Processing Lag > 10s (${var.environment})"
      severity     = "CRITICAL"
      filter       = <<-EOT
        resource.type = "pubsub_subscription"
        AND resource.labels.subscription_id = "coordinator-sub-${var.environment}"
        AND metric.type = "pubsub.googleapis.com/subscription/oldest_unacked_message_age"
      EOT
      threshold_value = 10
      comparison      = "COMPARISON_GT"
      duration        = "60s"
    }

    # P1: Cloud SQL replication lag > 30 seconds
    "p1-sql-replication-lag" = {
      display_name = "P1: Cloud SQL Replica Lag > 30s (${var.environment})"
      severity     = "CRITICAL"
      filter       = <<-EOT
        resource.type = "cloudsql_database"
        AND metric.type = "cloudsql.googleapis.com/database/replication/replica_lag"
      EOT
      threshold_value = 30
      comparison      = "COMPARISON_GT"
      duration        = "120s"
    }

    # P2: Agent task failure rate > 5%
    "p2-agent-failure-rate" = {
      display_name = "P2: Agent Task Failure Rate > 5% (${var.environment})"
      severity     = "ERROR"
      filter       = <<-EOT
        resource.type = "cloud_run_revision"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
        AND resource.labels.service_name != "api-gateway-${var.environment}"
      EOT
      threshold_value = 0.05
      comparison      = "COMPARISON_GT"
      duration        = "300s"
    }

    # P3: DLQ message count > 0
    "p3-dlq-messages" = {
      display_name = "P3: DLQ Message Count > 0 (${var.environment})"
      severity     = "WARNING"
      filter       = <<-EOT
        resource.type = "pubsub_topic"
        AND resource.labels.topic_id = "adt-events-dlq-${var.environment}"
        AND metric.type = "pubsub.googleapis.com/topic/send_message_operation_count"
      EOT
      threshold_value = 0
      comparison      = "COMPARISON_GT"
      duration        = "60s"
    }

    # P1: Uptime check failing (2 consecutive failures)
    "p1-api-uptime" = {
      display_name = "P1: API Gateway Uptime Check Failing (${var.environment})"
      severity     = "CRITICAL"
      filter       = <<-EOT
        metric.type = "monitoring.googleapis.com/uptime_check/check_passed"
        AND metric.labels.check_id = "${google_monitoring_uptime_check_config.api_health.uptime_check_id}"
      EOT
      threshold_value = 1
      comparison      = "COMPARISON_LT"
      duration        = "120s"
    }
  }
}

resource "google_monitoring_alert_policy" "alerts" {
  for_each = local.alert_policies

  display_name = each.value.display_name
  project      = var.project_id
  combiner     = "OR"
  severity     = each.value.severity

  conditions {
    display_name = each.value.display_name
    condition_threshold {
      filter          = each.value.filter
      comparison      = each.value.comparison
      threshold_value = each.value.threshold_value
      duration        = each.value.duration

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email_oncall.name]

  alert_strategy {
    auto_close = "604800s"  # Auto-close after 7 days if not acknowledged
  }
}
```

### 4. Custom Metrics (OpenTelemetry via Python SDK)

These are **not** Terraform resources — they are emitted by the application code. Terraform creates the metric descriptors:

```hcl
resource "google_monitoring_metric_descriptor" "vertex_token_usage" {
  description  = "Vertex AI token usage per agent call"
  display_name = "vertex_ai_token_usage"
  type         = "custom.googleapis.com/smarthandoff/vertex_ai_token_usage"
  metric_kind  = "GAUGE"
  value_type   = "INT64"
  project      = var.project_id

  labels {
    key         = "agent_type"
    value_type  = "STRING"
    description = "Agent type emitting the metric"
  }
}

resource "google_monitoring_metric_descriptor" "agent_task_duration" {
  description  = "Agent task processing duration in milliseconds"
  display_name = "agent_task_duration_ms"
  type         = "custom.googleapis.com/smarthandoff/agent_task_duration_ms"
  metric_kind  = "GAUGE"
  value_type   = "DOUBLE"
  project      = var.project_id

  labels {
    key        = "agent_type"
    value_type = "STRING"
  }
  labels {
    key        = "status"
    value_type = "STRING"
  }
}
```

## Acceptance Criteria

- [ ] `gcloud monitoring uptime-checks list --project={PROJECT}` shows `api-health-check` with status ACTIVE
- [ ] 6 alert policies created: `gcloud alpha monitoring policies list --project={PROJECT}` shows all P1/P2/P3 policies
- [ ] Manual trigger test: P1 API error rate alert triggers within 5 minutes when API returns 500s (inject errors in dev)
- [ ] DLQ P3 alert fires when a test message is placed in `adt-events-dlq-dev`
- [ ] Custom metric descriptors visible: `gcloud monitoring metrics list --project={PROJECT} --filter="metric.type:'custom.googleapis.com/smarthandoff'"` returns `vertex_ai_token_usage` and `agent_task_duration_ms`
- [ ] Cloud Trace receives traces: after a test API call, `gcloud trace list --project={PROJECT}` returns at least 1 trace

## Files to Create

```
infra/terraform/modules/monitoring/main.tf
infra/terraform/modules/monitoring/variables.tf
infra/terraform/modules/monitoring/outputs.tf
infra/terraform/modules/monitoring/README.md
```

## Notes

- OpenTelemetry trace context is propagated via `X-Cloud-Trace-Context` HTTP header — configured at the application code level (not Terraform), but the Cloud Trace API must be enabled (Task 002 API list includes `cloudtrace.googleapis.com`)
- Alert policy `severity` field (`CRITICAL`, `ERROR`, `WARNING`) maps to PagerDuty severity levels when integrated
- Uptime check `content_matchers` verifies the `/health` endpoint returns the expected JSON payload — not just a 200 status code
- `auto_close = "604800s"` prevents alert flooding from acknowledged-but-not-closed alerts accumulating over time
