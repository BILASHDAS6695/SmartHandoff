---
id: TASK-005
title: "Cloud Monitoring Alert — Export Job Failure Notification"
user_story: US-062
epic: EP-012
sprint: 2
layer: IaC / Observability
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [TASK-004, DR-017]
---

# TASK-005: Cloud Monitoring Alert — Export Job Failure Notification

> **Story:** US-062 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** IaC / Observability | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-062 AC Scenario 4 requires that the data team is notified via email when the nightly BigQuery export job fails. The Cloud Run job exits with code 1 on failure (implemented in TASK-003). This task provisions:

- A Cloud Monitoring log-based metric that fires when the Cloud Run job execution status is `FAILED`
- An alerting policy that triggers on the metric within a 5-minute evaluation window
- A notification channel (email) bound to the data team distribution list

All resources are provisioned via Terraform in the `monitoring` module.

**Design references:**
- US-062 AC Scenario 4 — Cloud Monitoring alert fires; data team notified via email
- design.md §3.1 — Cloud Monitoring + Cloud Logging for observability
- design.md §10 — Cross-cutting concerns: structured logs; alerting

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | Alert policy fires when `bq-export` Cloud Run job execution fails; email notification delivered to data team |

---

## Implementation Steps

### 1. Add alert resources to `infra/terraform/modules/monitoring/main.tf`

Append the following to the existing monitoring module (do not replace existing content):

```hcl
# ── BigQuery Export Job — Failure Alert ──────────────────────────────────────
# Detects Cloud Run job execution failures for the bq-export job.
# Triggered by US-062 AC Scenario 4: non-zero exit code from main.py.
#
# Design refs:
#   US-062 AC Scenario 4 — alert on export failure; email data team
#   design.md §10 — observability; structured logs

resource "google_logging_metric" "bq_export_failure" {
  project = var.project_id
  name    = "bq_export_job_failure_${var.environment}"

  filter = join(" AND ", [
    "resource.type=\"cloud_run_job\"",
    "resource.labels.job_name=\"bq-export-${var.environment}\"",
    "jsonPayload.severity=\"ERROR\"",
    "jsonPayload.message=~\"BigQuery nightly export job FAILED\"",
  ])

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    display_name = "BQ Export Job Failure (${var.environment})"
  }
}

resource "google_monitoring_notification_channel" "data_team_email" {
  project      = var.project_id
  display_name = "Data Team Email (${var.environment})"
  type         = "email"

  labels = {
    email_address = var.data_team_alert_email
  }
}

resource "google_monitoring_alert_policy" "bq_export_failure" {
  project      = var.project_id
  display_name = "BQ Export Job Failure — ${var.environment}"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Cloud Run job bq-export exited with failure"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.bq_export_failure.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"  # Fire immediately on first failure occurrence

      aggregations {
        alignment_period   = "300s"  # 5-minute evaluation window
        per_series_aligner = "ALIGN_COUNT"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.data_team_email.name,
  ]

  alert_strategy {
    auto_close = "86400s"  # Auto-close alert after 24 hours if no further failures
  }

  documentation {
    content = <<-EOT
      ## BigQuery Nightly Export Job Failure

      The `bq-export-${var.environment}` Cloud Run job has failed.

      **Immediate actions:**
      1. Check Cloud Logging for job logs: resource.type="cloud_run_job" AND resource.labels.job_name="bq-export-${var.environment}"
      2. Identify the root cause from the structured ERROR log entry
      3. If transient (Cloud SQL connectivity, BigQuery quota): re-trigger the job manually with the same EXPORT_DATE_OVERRIDE value
      4. If PHI schema violation detected: escalate to Data Privacy Officer immediately

      **Manual re-run command:**
      ```
      gcloud run jobs execute bq-export-${var.environment} --region=${var.region} --project=${var.project_id}
      ```

      **Runbook:** SmartHandoff Analytics — BQ Export Failure Runbook
    EOT
    mime_type = "text/markdown"
  }
}
```

### 2. Add required variables to `infra/terraform/modules/monitoring/variables.tf`

Append if not already present:

```hcl
variable "data_team_alert_email" {
  type        = string
  description = "Email address for data team alert notifications (BigQuery export failures)"
}
```

### 3. Wire new variable into environment `main.tf` calls

Update the existing `module "monitoring"` call in each environment `main.tf` to pass the new variable:

```hcl
module "monitoring" {
  # ... existing arguments ...
  data_team_alert_email = var.data_team_alert_email
}
```

Add to each environment `variables.tf`:

```hcl
variable "data_team_alert_email" {
  type        = string
  description = "Email for data team alert notifications"
}
```

Add to each environment `terraform.tfvars.example`:

```hcl
data_team_alert_email = "data-team@hospital.org"
```

---

## Definition of Done

- [ ] `google_logging_metric.bq_export_failure` filters on structured log message `"BigQuery nightly export job FAILED"` for the correct job name per environment
- [ ] `google_monitoring_alert_policy.bq_export_failure` has `threshold_value = 0` and `comparison = "COMPARISON_GT"` — fires on first failure occurrence
- [ ] `google_monitoring_notification_channel.data_team_email` bound to `var.data_team_alert_email`
- [ ] Alert documentation block includes manual re-run `gcloud` command and escalation path for PHI violations
- [ ] `data_team_alert_email` variable added to `monitoring/variables.tf` and all three environment `variables.tf` + `terraform.tfvars.example`
- [ ] `terraform validate` passes for the `monitoring` module and all environments
- [ ] Alert manually verified in dev: trigger job failure (e.g., invalid DB credentials) → confirm alert fires in Cloud Monitoring console

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-003 | Task | `main.py` must exit `1` with structured ERROR log for the metric filter to match |
| TASK-004 | Task | Cloud Run job `bq-export-{environment}` must exist before alert can reference it |
| `monitoring` module | Existing | New resources appended to existing module — do not replace existing alerts |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/main.tf` | Update — append BQ export failure metric + alert policy + email notification channel |
| `infra/terraform/modules/monitoring/variables.tf` | Update — add `data_team_alert_email` variable |
| `infra/terraform/environments/dev/main.tf` | Update — pass `data_team_alert_email` to monitoring module |
| `infra/terraform/environments/dev/variables.tf` | Update — add `data_team_alert_email` |
| `infra/terraform/environments/dev/terraform.tfvars.example` | Update — add example value |
| `infra/terraform/environments/staging/main.tf` | Update — same as dev |
| `infra/terraform/environments/staging/variables.tf` | Update — same as dev |
| `infra/terraform/environments/staging/terraform.tfvars.example` | Update — same as dev |
| `infra/terraform/environments/prod/main.tf` | Update — same as dev |
| `infra/terraform/environments/prod/variables.tf` | Update — same as dev |
| `infra/terraform/environments/prod/terraform.tfvars.example` | Update — same as dev |
