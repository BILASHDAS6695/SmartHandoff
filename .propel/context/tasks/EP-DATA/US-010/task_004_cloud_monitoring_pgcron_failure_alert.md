---
id: TASK-004
title: "Configure Cloud Monitoring Alert — pg_cron Job Failure Detection via cron.job_run_details"
user_story: US-010
epic: EP-DATA
sprint: 1
layer: Infrastructure / Observability
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, TASK-003]
---

# TASK-004: Configure Cloud Monitoring Alert — pg_cron Job Failure Detection via cron.job_run_details

> **Story:** US-010 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Infrastructure / Observability | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-010 Acceptance Criteria Scenario 4:

> **Given** a pg_cron archival job fails due to a transient error  
> **When** the job raises an exception  
> **Then** an error entry appears in `cron.job_run_details` and a Cloud Monitoring alert fires within 5 minutes to notify the on-call engineer.

US-010 DoD: *"Cloud Monitoring alert configured on `cron.job_run_details` error status"*.

### How Cloud SQL Exposes pg_cron Failures

When a pg_cron job fails:
1. PostgreSQL records an error in the `cron.job_run_details` system table with `status = 'failed'`.
2. Cloud SQL's managed log export forwards all `postgresql.log` entries to **Cloud Logging** as structured log entries (resource type: `cloudsql_database`).
3. The `RAISE WARNING` calls in `archive_old_encounters()` and `purge_exported_audit_logs()` (TASK-002/003) produce `WARNING`-severity PostgreSQL log entries.

The alert mechanism is a **log-based metric** in Cloud Monitoring that counts PostgreSQL log entries matching the pg_cron failure pattern, combined with an alert policy that fires when the count exceeds zero.

### Terraform Scope

The monitoring module (`infra/terraform/modules/monitoring/main.tf`) is currently a stub. This task adds pg_cron alert resources to the stub. The full monitoring module implementation is tracked under EP-TECH; this task adds only the resources required for US-010 DoD.

---

## Acceptance Criteria Addressed

| US-010 AC | Requirement |
|---|---|
| **Scenario 4** | `cron.job_run_details` error status → Cloud Monitoring alert fires within 5 minutes |
| **DoD** | Cloud Monitoring alert configured on `cron.job_run_details` error status |

---

## Implementation Steps

### 1. Add Log-Based Metric to monitoring/main.tf

A log-based metric counts PostgreSQL log lines that contain pg_cron failure signals. The filter targets Cloud SQL database logs with `FAILED` or `WARNING` messages from the archival/purge functions.

Add to `infra/terraform/modules/monitoring/main.tf`:

```hcl
# ── Log-based metric: pg_cron archival/purge job failures ────────────────────
resource "google_logging_metric" "pgcron_job_failure" {
  project = var.project_id
  name    = "pgcron_archival_job_failure_count"

  description = "Counts PostgreSQL log entries indicating pg_cron archival or purge job failures. Triggers on FAILED status in cron.job_run_details or RAISE WARNING from archive/purge functions."

  filter = <<-EOT
    resource.type="cloudsql_database"
    resource.labels.project_id="${var.project_id}"
    (
      textPayload=~"archive_old_encounters FAILED"
      OR textPayload=~"purge_exported_audit_logs FAILED"
      OR textPayload=~"cron.*failed"
    )
    severity=("WARNING" OR "ERROR" OR "CRITICAL")
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    labels {
      key         = "job_name"
      value_type  = "STRING"
      description = "pg_cron job name extracted from log message"
    }
  }

  label_extractors = {
    "job_name" = "EXTRACT(textPayload, '(archive_old_encounters|purge_exported_audit_logs)')"
  }
}

# ── Notification channel: email to on-call ───────────────────────────────────
resource "google_monitoring_notification_channel" "oncall_email_pgcron" {
  project      = var.project_id
  display_name = "On-Call Email — pg_cron Failures (${var.environment})"
  type         = "email"

  labels = {
    email_address = var.oncall_email
  }
}

# ── Alert policy: fires when pg_cron failure count > 0 ───────────────────────
resource "google_monitoring_alert_policy" "pgcron_job_failure_alert" {
  project      = var.project_id
  display_name = "pg_cron Archival/Purge Job Failure — ${upper(var.environment)}"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "pg_cron archival/purge failure count > 0 (5-min window)"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/pgcron_archival_job_failure_count\" resource.type=\"cloudsql_database\""
      duration        = "0s"   # Fire immediately when threshold is crossed
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period     = "300s"  # 5-minute window (Scenario 4: alert within 5 minutes)
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.oncall_email_pgcron.id,
  ]

  alert_strategy {
    auto_close = "604800s"  # Auto-close after 7 days if not manually resolved
  }

  documentation {
    content   = <<-EOT
      ## pg_cron Archival/Purge Job Failure

      One or more of the following pg_cron jobs has failed:
      - **archive-old-encounters** (nightly 03:00 UTC): 7-year encounter archival
      - **purge-old-audit-logs** (weekly Sunday 04:00 UTC): 6-year audit log purge

      ### Investigation Steps
      1. Check `cron.job_run_details` for the failing job:
         ```sql
         SELECT jobid, jobname, start_time, end_time, status, return_message
         FROM cron.job_run_details
         WHERE status = 'failed'
         ORDER BY start_time DESC
         LIMIT 10;
         ```
      2. Check Cloud Logging for `archive_old_encounters FAILED` or `purge_exported_audit_logs FAILED`.
      3. Verify `encounter_archive` table is accessible and not out of storage.
      4. Verify `audit_log_archive_queue` export status (`exported_at IS NOT NULL`) if purge is failing.

      ### Escalation
      If not resolved within 1 hour, escalate to the Compliance Officer — HIPAA retention SLA may be at risk.

      **Reference:** US-010, DR-006, BR-022, BR-023
    EOT
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.pgcron_job_failure]
}
```

### 2. Add Output to monitoring/outputs.tf

```hcl
output "pgcron_failure_alert_policy_name" {
  description = "Name of the Cloud Monitoring alert policy for pg_cron job failures"
  value       = google_monitoring_alert_policy.pgcron_job_failure_alert.name
}
```

### 3. Verify the monitoring Module Is Called from the Environment Root

Confirm `infra/terraform/environments/dev/main.tf` (and staging/prod equivalents) include the monitoring module. If the stub module call is missing:

```bash
grep -n "monitoring" infra/terraform/environments/dev/main.tf
```

If absent, add:

```hcl
module "monitoring" {
  source              = "../../modules/monitoring"
  project_id          = var.project_id
  environment         = var.environment
  api_domain          = var.api_domain
  oncall_email        = var.oncall_email
  slack_alert_channel = var.slack_alert_channel
}
```

### 4. Apply Terraform (Dev Environment)

```bash
cd infra/terraform/environments/dev

# Review changes
terraform plan -var-file="terraform.tfvars"

# Apply
terraform apply -var-file="terraform.tfvars"
```

Confirm in the GCP Console:
- **Cloud Monitoring → Alerting → Alert Policies**: policy `pg_cron Archival/Purge Job Failure — DEV` is active.
- **Cloud Monitoring → Metrics Explorer**: metric `pgcron_archival_job_failure_count` is visible under `cloudsql_database`.

### 5. Smoke Test the Alert (Optional — Dev Environment Only)

To verify the alert fires:

```bash
# Directly insert a fake failure log entry to Cloud Logging (requires gcloud)
gcloud logging write "projects/${PROJECT_ID}/logs/cloudsql.googleapis.com%2Fpostgresql.log" \
  '{
    "textPayload": "WARNING:  archive_old_encounters FAILED: division by zero  SQLSTATE: 22012",
    "severity": "WARNING",
    "resource": {
      "type": "cloudsql_database",
      "labels": {
        "project_id": "'"${PROJECT_ID}"'",
        "database_id": "'"${CLOUD_SQL_INSTANCE_ID}"'"
      }
    }
  }' \
  --severity=WARNING
```

Within 5 minutes, the alert should appear in Cloud Monitoring → Active Alerts, and the on-call email should receive a notification.

---

## File Checklist

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/main.tf` | Add log-based metric + notification channel + alert policy |
| `infra/terraform/modules/monitoring/outputs.tf` | Add `pgcron_failure_alert_policy_name` output |

---

## Definition of Done Mapping

| DoD Item | Met By |
|---|---|
| Cloud Monitoring alert configured on `cron.job_run_details` error status | `google_monitoring_alert_policy.pgcron_job_failure_alert` Terraform resource |
| Alert fires within 5 minutes | `alignment_period = "300s"` in alert condition |
| On-call engineer notified | `notification_channels` linked to `oncall_email` |
