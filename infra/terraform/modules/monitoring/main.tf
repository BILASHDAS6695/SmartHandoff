# monitoring module
# Provisions canary error-rate alert policies, Pub/Sub rollback channels,
# and Cloud Build rollback triggers for all 10 SmartHandoff services.
# Implemented by: EP-TECH / US-003 / TASK-005

locals {
  # CI/CD services that have canary deployments monitored for error rate spikes
  cicd_services = toset([
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "comms-agent", "ml-inference", "notification-svc",
    "audit-svc", "portal-bff",
  ])
}

# ── Pub/Sub topics for canary rollback notifications ─────────────────────────
resource "google_pubsub_topic" "canary_rollback" {
  for_each = local.cicd_services
  name     = "smarthandoff-canary-rollback-${each.key}-${var.environment}"
  project  = var.project_id

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    purpose     = "canary-rollback"
  }
}

# Grant the Cloud Monitoring service agent permission to publish to these topics
resource "google_pubsub_topic_iam_member" "monitoring_publisher" {
  for_each = local.cicd_services
  topic    = google_pubsub_topic.canary_rollback[each.key].name
  project  = var.project_id
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:service-${var.project_number}@gcp-sa-monitoring-notification.iam.gserviceaccount.com"
}

# ── Cloud Monitoring notification channels (Pub/Sub) ─────────────────────────
resource "google_monitoring_notification_channel" "canary_rollback_pubsub" {
  for_each     = local.cicd_services
  display_name = "canary-rollback-pubsub-${each.key}-${var.environment}"
  type         = "pubsub"
  project      = var.project_id

  labels = {
    topic = google_pubsub_topic.canary_rollback[each.key].id
  }
}

# Email notification channel for all alert types
# moved block handles state migration from the legacy "oncall_email" resource name.
resource "google_monitoring_notification_channel" "email" {
  display_name = "SmartHandoff On-Call Email (${var.environment})"
  type         = "email"
  project      = var.project_id

  labels = {
    email_address = var.oncall_email
  }

  user_labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

# Migrate state from legacy resource name — safe no-op on fresh applies.
moved {
  from = google_monitoring_notification_channel.oncall_email
  to   = google_monitoring_notification_channel.email
}

# ── Canary error-rate alert policy (per service) ─────────────────────────────
# Fires when 5xx error rate > 1% on any revision of the service within 5 minutes.
# Notifies: Pub/Sub (→ cicd-alert-handler → Cloud Build rollback) + email.
resource "google_monitoring_alert_policy" "canary_error_rate" {
  for_each     = local.cicd_services
  display_name = "smarthandoff-${each.key}-canary-error-rate-${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "5xx error rate > 1% on ${each.key}-${var.environment} (5-min window)"

    condition_threshold {
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND resource.labels.service_name = "${each.key}-${var.environment}"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT

      aggregations {
        alignment_period     = "300s"          # 5-minute observation window
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.revision_name"]
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 0.01   # 1% error rate threshold
      duration        = "0s"   # Fire immediately when threshold is crossed

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.canary_rollback_pubsub[each.key].id,
    google_monitoring_notification_channel.email.id,
  ]

  alert_strategy {
    auto_close = "1800s"   # Auto-resolve after 30 minutes if error rate drops
  }

  documentation {
    content   = "Canary error rate exceeded 1% for `${each.key}-${var.environment}`. Automated rollback triggered via Pub/Sub → cicd-alert-handler → Cloud Build rollback job. Check Cloud Run logs for root cause."
    mime_type = "text/markdown"
  }
}

# ── Cloud Build rollback triggers (per service) ───────────────────────────────
# Triggered by the cicd-alert-handler Cloud Run service via the Cloud Build API.
# Uses cloudbuild-rollback.yaml to restore 100% traffic to the previous stable revision.
resource "google_cloudbuild_trigger" "rollback" {
  for_each    = local.cicd_services
  name        = "smarthandoff-${each.key}-rollback-${var.environment}"
  description = "Automated canary rollback for ${each.key} (${var.environment})"
  project     = var.project_id
  location    = "global"

  # Rollback is triggered programmatically (not by a branch push) —
  # use webhook trigger type so it can be invoked via the Cloud Build API
  webhook_config {
    secret = google_secret_manager_secret_version.rollback_webhook_secret[each.key].id
  }

  filename = ".cloudbuild/cloudbuild-rollback.yaml"

  substitutions = {
    _SERVICE_NAME = each.key
    _ENVIRONMENT  = var.environment
    _REGION       = var.region
    _PROJECT_ID   = var.project_id
  }

  service_account = "projects/${var.project_id}/serviceAccounts/${var.cloudbuild_sa_email}"
}

# Webhook secrets for rollback triggers (one per service)
resource "google_secret_manager_secret" "rollback_webhook_secret" {
  for_each  = local.cicd_services
  secret_id = "cloudbuild-rollback-webhook-${each.key}-${var.environment}"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    purpose     = "cloudbuild-webhook"
  }
}

resource "google_secret_manager_secret_version" "rollback_webhook_secret" {
  for_each    = local.cicd_services
  secret      = google_secret_manager_secret.rollback_webhook_secret[each.key].id
  secret_data = "PLACEHOLDER_CHANGE_BEFORE_DEPLOY"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  US-004 — Cloud Monitoring Dashboards & Alerting                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── PagerDuty notification channel (P1/P2 pages) ────────────────────────────
# Only created when pagerduty_integration_key is supplied (non-empty).
resource "google_monitoring_notification_channel" "pagerduty" {
  count        = var.pagerduty_integration_key != "" ? 1 : 0
  project      = var.project_id
  display_name = "SmartHandoff PagerDuty (${var.environment})"
  type         = "pagerduty"

  sensitive_labels {
    service_key = var.pagerduty_integration_key
  }

  user_labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

locals {
  # Build the notification channel list for P1 alerts (email always present;
  # PagerDuty added only when the integration key is configured).
  p1_channels = concat(
    [google_monitoring_notification_channel.email.name],
    var.pagerduty_integration_key != "" ? [google_monitoring_notification_channel.pagerduty[0].name] : []
  )

  # P2/P3 alerts go to email only (not PagerDuty — lower severity).
  p2_p3_channels = [google_monitoring_notification_channel.email.name]

  # Services to monitor with uptime checks (US-004 AC Scenario 3).
  monitored_services = {
    "api-gateway"          = "api-gateway"
    "hl7-listener"         = "hl7-listener"
    "coordinator-agent"    = "coordinator-agent"
    "docs-agent"           = "docs-agent"
    "medrecon-agent"       = "medrecon-agent"
    "bed-management-agent" = "bed-management-agent"
    "followup-care-agent"  = "followup-care-agent"
    "patient-comms-agent"  = "patient-comms-agent"
    "ml-inference"         = "ml-inference"
    "notification-svc"     = "notification-svc"
  }
}

# ── P1 Alert: Error Rate >1% for 60 s ────────────────────────────────────────
resource "google_monitoring_alert_policy" "p1_error_rate" {
  project      = var.project_id
  display_name = "[P1] SmartHandoff — Error Rate >1% (${var.environment})"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run request error rate >1% for 60s"

    condition_monitoring_query_language {
      query = <<-EOT
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

  notification_channels = local.p1_channels

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

# ── P2 Alert: Request Latency p95 >5 s for 60 s ─────────────────────────────
resource "google_monitoring_alert_policy" "p2_latency_p95" {
  project      = var.project_id
  display_name = "[P2] SmartHandoff — Request Latency p95 >5s (${var.environment})"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run request latency p95 >5s for 60s"

    condition_monitoring_query_language {
      query = <<-EOT
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

  notification_channels = local.p2_p3_channels

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }

  user_labels = {
    severity    = "p2"
    environment = var.environment
    managed_by  = "terraform"
  }

  documentation {
    content   = "P2 — Request latency p95 exceeds 5 second SLA. Check service resource limits and upstream dependencies. Runbook: https://wiki.internal/runbooks/smarthandoff-p2-latency"
    mime_type = "text/markdown"
  }
}

# ── P3 Alert: DLQ message count >0 for 60 s ─────────────────────────────────
resource "google_monitoring_alert_policy" "p3_dlq_messages" {
  project      = var.project_id
  display_name = "[P3] SmartHandoff — DLQ Messages Pending (${var.environment})"
  combiner     = "OR"

  conditions {
    display_name = "Pub/Sub DLQ subscription has undelivered messages"

    condition_monitoring_query_language {
      query = <<-EOT
        fetch pubsub_subscription
        | metric 'pubsub.googleapis.com/subscription/num_undelivered_messages'
        | filter (resource.labels.project_id == '${var.project_id}')
        | filter (resource.labels.subscription_id =~ '.*-dlq-.*')
        | align next_older(60s)
        | group_by [], [max_dlq_depth: max(val())]
        | condition max_dlq_depth > 0
      EOT
      duration = "60s"
    }
  }

  notification_channels = local.p2_p3_channels

  alert_strategy {
    notification_rate_limit {
      period = "600s"
    }
    auto_close = "3600s"
  }

  user_labels = {
    severity    = "p3"
    environment = var.environment
    managed_by  = "terraform"
  }

  documentation {
    content   = "P3 — Dead-letter queue has pending messages. Messages may be failing after max delivery attempts. Investigate subscriber errors. Runbook: https://wiki.internal/runbooks/smarthandoff-p3-dlq"
    mime_type = "text/markdown"
  }
}

# ── Uptime checks — one per service (60-second interval) ────────────────────
resource "google_monitoring_uptime_check_config" "service_health" {
  for_each     = local.monitored_services
  project      = var.project_id
  display_name = "SmartHandoff ${each.key} /health (${var.environment})"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true

    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "${each.value}.${var.api_domain}"
    }
  }

  user_labels = {
    service     = each.key
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ── Uptime failure alert — fires when any service fails 2 consecutive checks ─
# 2 consecutive failures at 60s interval = 120s detection window (AC Scenario 3).
resource "google_monitoring_alert_policy" "uptime_failure" {
  project      = var.project_id
  display_name = "[P1] SmartHandoff — Uptime Check Failure (${var.environment})"
  combiner     = "OR"

  dynamic "conditions" {
    for_each = google_monitoring_uptime_check_config.service_health

    content {
      display_name = "${conditions.value.display_name} — consecutive failures"

      condition_threshold {
        filter   = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id=\"${conditions.value.uptime_check_id}\""
        duration = "120s"

        comparison      = "COMPARISON_LT"
        threshold_value = 1

        aggregations {
          alignment_period     = "60s"
          per_series_aligner   = "ALIGN_NEXT_OLDER"
          cross_series_reducer = "REDUCE_COUNT_FALSE"
          group_by_fields      = ["resource.labels.*"]
        }

        trigger {
          count = 2
        }
      }
    }
  }

  notification_channels = local.p1_channels

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
    content   = "P1 — Service /health endpoint returning non-2xx for 2+ consecutive checks (60s interval). The affected service appears as 'failing' on the SmartHandoff Operations dashboard. Runbook: https://wiki.internal/runbooks/smarthandoff-p1-uptime"
    mime_type = "text/markdown"
  }
}

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  US-010 — pg_cron Archival / Purge Job Failure Alerting                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── Log-based metric: pg_cron archival/purge job failure count ────────────────
# Counts WARNING/ERROR log lines emitted by archive_old_encounters() and
# purge_exported_audit_logs() when they hit the EXCEPTION WHEN OTHERS block.
resource "google_logging_metric" "pgcron_job_failure" {
  project = var.project_id
  name    = "pgcron_archival_job_failure_count"

  filter = <<-EOT
    resource.type="cloudsql_database"
    (
      textPayload=~"archive_old_encounters FAILED"
      OR textPayload=~"purge_exported_audit_logs FAILED"
      OR textPayload=~"cron.*failed"
    )
    severity=("WARNING" OR "ERROR" OR "CRITICAL")
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "pg_cron archival job failure count"

    labels {
      key         = "job_name"
      value_type  = "STRING"
      description = "pg_cron job name extracted from the failure log message"
    }
  }

  label_extractors = {
    "job_name" = "EXTRACT(textPayload, \"(archive_old_encounters|purge_exported_audit_logs)\")"
  }
}

# ── Alert policy: pg_cron job failure ────────────────────────────────────────
# Fires within 5 minutes of the first failure log line (alignment_period=300s).
# Notifies the on-call email channel (already provisioned in this module).
resource "google_monitoring_alert_policy" "pgcron_job_failure_alert" {
  project      = var.project_id
  display_name = "pg_cron Archival/Purge Job Failure — ${upper(var.environment)}"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "pg_cron archival/purge error count > 0 (5-min window)"

    condition_threshold {
      filter = <<-EOT
        resource.type="cloudsql_database"
        AND metric.type="logging.googleapis.com/user/${google_logging_metric.pgcron_job_failure.name}"
      EOT

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  alert_strategy {
    auto_close = "604800s"   # Auto-resolve after 7 days per TASK-004 spec
  }

  user_labels = {
    severity    = "p2"
    environment = var.environment
    managed_by  = "terraform"
    component   = "data-retention"
  }

  documentation {
    content   = <<-DOC
      **pg_cron Archival/Purge Job Failure — ${upper(var.environment)}**

      One or more of the HIPAA-mandated data retention pg_cron jobs has failed.

      **Affected jobs:**
      - `archive-old-encounters` (nightly 03:00 UTC) — moves 7-year-old encounter rows to encounter_archive
      - `purge-old-audit-logs` (Sunday 04:00 UTC) — deletes confirmed-exported audit_log rows older than 6 years

      **Investigation steps:**
      1. Check Cloud SQL logs: `SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 20;`
      2. Check for error details: filter `textPayload =~ "FAILED: "` in Cloud Logging
      3. Verify pg_cron is enabled: `SHOW cloudsql.enable_pgcron;`
      4. Confirm encounter_archive and audit_log_archive_queue tables are accessible
      5. Check available disk space on the Cloud SQL instance

      **Escalation:** If not self-resolved within 1 hour, escalate to the on-call DBA and Compliance Officer.
      Non-resolution within 24 hours constitutes a potential HIPAA breach (45 CFR §164.312(b)).

      Runbook: https://wiki.internal/runbooks/smarthandoff-pgcron-data-retention
    DOC
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.pgcron_job_failure]
}

