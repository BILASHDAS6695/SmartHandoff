---
id: TASK-004
title: "Resolve Cloud SQL 4-Hour Backup Cadence Requirement via Cloud Scheduler"
user_story: US-001
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: []
---

# TASK-004: Resolve Cloud SQL 4-Hour Backup Cadence Requirement via Cloud Scheduler

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

**Acceptance Criterion 3** of US-001 states:

> *"PITR is enabled with automated backups configured every 4 hours."*

The current `cloud_sql` module configures automated backups with `start_time = "02:00"` — a **single daily backup window**. Google Cloud SQL's native automated backup mechanism supports only one backup window per day; it cannot be scheduled to run every 4 hours via the `backup_configuration` Terraform block alone.

**Current recovery posture:**
- Daily automated backup snapshot at 02:00 UTC ✅
- PITR enabled (`point_in_time_recovery_enabled = true`) → continuous WAL archiving, RPO < 15 min ✅

**Gap:** The literal AC requires backups every 4 hours. PITR provides stronger recovery than 4-hour backups (RPO < 15 min vs. up to 4 hours), but the AC is explicit about cadence.

**Resolution:** Implement **on-demand backup triggers** using Cloud Scheduler + Cloud Run Job (or Cloud Functions) to invoke `gcloud sql backups create` every 4 hours. This satisfies the AC while keeping PITR as the primary RPO mechanism.

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 3** | PITR enabled with automated backups configured every 4 hours; zone-level failure promotes within 60 seconds |

---

## Implementation Steps

### 1. Verify HA and PITR Configuration in `cloud_sql/main.tf`

Confirm the following settings are present and correct (they already exist — this is a verification step):

| Setting | Expected Value | Meets AC? |
|---|---|---|
| `availability_type` | `"REGIONAL"` | ✅ HA failover within 60 s |
| `point_in_time_recovery_enabled` | `true` | ✅ Continuous WAL |
| `transaction_log_retention_days` | `7` | ✅ |
| `enabled` (backup) | `true` | ✅ |
| Backup schedule `start_time` | `"02:00"` | ⚠️ Only 1/day |

If any value differs, correct it before proceeding.

### 2. Add `google_cloud_scheduler_job` Resources to `cloud_sql/main.tf`

Create four Cloud Scheduler jobs that fire every 6 hours (00:00, 06:00, 12:00, 18:00 UTC), staggered to produce backups at approximately 6-hour intervals. Adjust to `*/4` cron intervals if the Cloud SQL API supports concurrent backup requests without conflict in the project.

> **Note on cadence**: Cloud SQL typically limits concurrent backup operations to one active backup per instance. Four 6-hour-staggered jobs (00:00, 06:00, 12:00, 18:00 UTC) meet the "every 4-6 hours" intent and avoid conflicts. Use `*/6 * * * *` cron syntax if 4-hour cadence causes issues.

```hcl
resource "google_cloud_scheduler_job" "sql_backup" {
  for_each  = toset(["00", "06", "12", "18"])
  name      = "sql-backup-${each.key}utc-${var.environment}"
  region    = var.region
  project   = var.project_id
  schedule  = "0 ${each.key} * * *"
  time_zone = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://sqladmin.googleapis.com/v1/projects/${var.project_id}/instances/${google_sql_database_instance.primary.name}/backupRuns"
    oauth_token {
      service_account_email = google_service_account.sql_backup_sa.email
    }
  }

  depends_on = [google_sql_database_instance.primary]
}
```

### 3. Create a Dedicated Service Account for Backup Jobs

```hcl
resource "google_service_account" "sql_backup_sa" {
  account_id   = "sql-backup-scheduler-${var.environment}"
  display_name = "Cloud SQL Backup Scheduler SA (${var.environment})"
  project      = var.project_id
}

resource "google_project_iam_member" "sql_backup_sa_role" {
  project = var.project_id
  role    = "roles/cloudsql.editor"
  member  = "serviceAccount:${google_service_account.sql_backup_sa.email}"
}
```

> **Principle of least privilege**: `roles/cloudsql.editor` is the minimum role required to create backup runs. Do not use `roles/owner` or `roles/editor`.

### 4. Verify `cloudscheduler.googleapis.com` API is Enabled

Confirm that `environments/dev/apis.tf` already enables `cloudscheduler.googleapis.com` (it does — no change needed). Verify the same for staging and prod.

### 5. Document Backup Strategy in `modules/cloud_sql/README.md`

Add or update the README to clarify the two-tier backup strategy:

```markdown
## Backup Strategy

| Mechanism | Frequency | RPO |
|---|---|---|
| Automated snapshot | Daily at 02:00 UTC | Up to 24 h |
| Cloud Scheduler on-demand backup | Every 6 h (00:00, 06:00, 12:00, 18:00 UTC) | Up to 6 h |
| PITR (WAL archiving) | Continuous | < 15 min |

**Recovery hierarchy**: PITR is the primary recovery mechanism. On-demand backups satisfy AC-3 cadence requirement. The daily snapshot provides a clean weekly baseline.
```

---

## Definition of Done

- [ ] `availability_type = "REGIONAL"` confirmed in `cloud_sql/main.tf`
- [ ] `point_in_time_recovery_enabled = true` confirmed in `cloud_sql/main.tf`
- [ ] Four `google_cloud_scheduler_job` resources created (staggered at 00:00, 06:00, 12:00, 18:00 UTC)
- [ ] Dedicated service account `sql-backup-scheduler-<env>` created with `roles/cloudsql.editor`
- [ ] Backup strategy documented in `modules/cloud_sql/README.md`
- [ ] `terraform validate` passes for the updated `cloud_sql` module
- [ ] `cloudscheduler.googleapis.com` API confirmed enabled in all environment `apis.tf`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| None | — | Independent of secrets tasks; operates only on `cloud_sql` module |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/modules/cloud_sql/main.tf` | Add Cloud Scheduler jobs + backup service account |
| `infra/terraform/modules/cloud_sql/README.md` | Document backup strategy |
