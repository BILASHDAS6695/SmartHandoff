---
id: TASK-006
title: "Code Review and US-010 Definition of Done Sign-Off"
user_story: US-010
epic: EP-DATA
sprint: 1
layer: Engineering Process
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer (Reviewer) + Compliance Officer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Code Review and US-010 Definition of Done Sign-Off

> **Story:** US-010 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Engineering Process | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final gate task for US-010. US-010 implements HIPAA-mandated automated data retention — directly supporting 45 CFR §164.530(j) (record retention) and 45 CFR §164.312(b) (audit controls). The DoD requires **both** a Backend Engineer review and a Compliance Officer sign-off before code merges to `main`.

The review covers four areas:
1. **Archival correctness** — the `archive_old_encounters()` function genuinely moves 7-year-old rows and deletes originals without data loss or premature deletion.
2. **Purge safety** — the `purge_exported_audit_logs()` function only deletes rows confirmed exported to the WORM GCS bucket; no row is purged without confirmed GCS copy.
3. **WORM bucket configuration** — the Cloud Storage bucket has a locked retention policy that prevents objects from being deleted before the 6-year period expires.
4. **Monitoring coverage** — the Cloud Monitoring alert fires within 5 minutes of any pg_cron failure.

No production code from US-010 may merge without this sign-off.

---

## Review Checklist

### encounter_archive Table (TASK-001)

| Item | Check |
|---|---|
| `encounter_archive` schema matches `encounter` exactly except for `archived_at` column | ☐ |
| `archived_at` column has `NOT NULL` constraint with `server_default = now()` | ☐ |
| No foreign key constraints on `encounter_archive` (denormalised archive — intentional) | ☐ |
| `app_write` role has no INSERT/UPDATE/DELETE privileges on `encounter_archive` | ☐ |
| `compliance_reader` role has SELECT on `encounter_archive` | ☐ |
| Indexes on `patient_id`, `archived_at`, `discharge_date` are present | ☐ |
| `downgrade()` drops table and indexes in correct order | ☐ |
| `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` passes cleanly | ☐ |

### Encounter Archival pg_cron Job (TASK-002)

| Item | Check |
|---|---|
| `archive_old_encounters()` function uses `SECURITY DEFINER` | ☐ |
| WHERE clause is `discharge_date < now() - INTERVAL '7 years'` — NOT `created_at` | ☐ |
| `FOR UPDATE SKIP LOCKED` prevents blocking concurrent transactions on `encounter` | ☐ |
| Batch size is 500 — no full-table lock risk | ☐ |
| INSERT into `encounter_archive` happens BEFORE DELETE from `encounter` in the same loop iteration | ☐ |
| `EXCEPTION WHEN OTHERS` block re-raises after logging — failure is not silently swallowed | ☐ |
| pg_cron job schedule is `0 3 * * *` (03:00 UTC daily) | ☐ |
| `downgrade()` calls `cron.unschedule('archive-old-encounters')` BEFORE dropping function | ☐ |
| `soft_deleted` rows (`deleted_at IS NOT NULL`) are correctly excluded from archival | ☐ |

### Audit Log Purge pg_cron Job (TASK-003)

| Item | Check |
|---|---|
| `purge_exported_audit_logs()` function uses `SECURITY DEFINER` | ☐ |
| WHERE clause checks BOTH `created_at < now() - INTERVAL '2190 days'` AND `q.exported_at IS NOT NULL` | ☐ |
| Rows with `exported_at IS NULL` (not yet exported to GCS) are NOT deleted under any condition | ☐ |
| Rows within 6-year window are NOT deleted even if `exported_at IS NOT NULL` | ☐ |
| The purge job also cleans up corresponding `audit_log_archive_queue` rows | ☐ |
| `SECURITY DEFINER` bypass of RLS is documented and justified (purge is the intended lifecycle termination) | ☐ |
| pg_cron job schedule is `0 4 * * 0` (Sunday 04:00 UTC) — AFTER nightly archive job at 02:00 UTC | ☐ |
| `downgrade()` calls `cron.unschedule('purge-old-audit-logs')` BEFORE dropping function | ☐ |

### Cloud Storage WORM Bucket (TASK-003 + Terraform)

| Item | Check |
|---|---|
| Terraform resource `google_storage_bucket.audit_log_archive` exists in `infra/terraform/modules/storage/main.tf` | ☐ |
| `retention_policy.retention_period = 189216000` (6 years in seconds) | ☐ |
| `retention_policy.is_locked = true` — retention lock cannot be shortened | ☐ |
| `uniform_bucket_level_access = true` — no ACL bypass | ☐ |
| Bucket is NOT publicly accessible | ☐ |
| Bucket labels include `phi_data = "true"` for compliance inventory | ☐ |

### Cloud Monitoring Alert (TASK-004)

| Item | Check |
|---|---|
| Log-based metric `pgcron_archival_job_failure_count` is deployed in Terraform | ☐ |
| Filter matches both `archive_old_encounters FAILED` and `purge_exported_audit_logs FAILED` log patterns | ☐ |
| Alert condition alignment_period is `300s` (5 minutes) — meets Scenario 4 SLA | ☐ |
| Notification channel is linked to the on-call email (`var.oncall_email`) | ☐ |
| Alert documentation includes investigation steps and escalation path | ☐ |
| Alert policy is verified active in Cloud Monitoring dev environment | ☐ |

### Integration Tests (TASK-005)

| Item | Check |
|---|---|
| 6 integration tests pass with 0 failures in testcontainers | ☐ |
| Expired encounter test uses `discharge_date = now() - 7 years - 30 days` (clearly past boundary) | ☐ |
| Recent encounter test uses `discharge_date = now() - 5 years` (clearly within boundary) | ☐ |
| Unexported audit log test verifies `exported_at = NULL` row is NOT purged | ☐ |
| `test_cron_jobs_registered` is correctly skipped in testcontainers and passes on Cloud SQL dev | ☐ |
| No PHI data in test fixtures — synthetic UUIDs only | ☐ |
| Test file has no hardcoded database credentials | ☐ |

### Definition of Done — Final Checklist

| DoD Item | Owner | Status |
|---|---|---|
| Alembic migration enables `pg_cron` extension and registers all retention jobs | Backend Engineer | ☐ |
| `encounter_archive` table created with identical schema to `encounter` plus `archived_at` timestamp | Backend Engineer | ☐ |
| pg_cron job for encounter archival: nightly at 03:00 UTC, moves rows older than 7 years | Backend Engineer | ☐ |
| pg_cron job for audit log purge: weekly, exports to Cloud Storage then deletes rows older than 6 years | Backend Engineer | ☐ |
| Cloud Storage export uses WORM (retention policy locked) bucket for audit log archives | Backend Engineer | ☐ |
| Cloud Monitoring alert configured on `cron.job_run_details` error status | Backend Engineer | ☐ |
| Unit tests verify archival logic with synthetic past-dated records | Backend Engineer | ☐ |
| Code reviewed and approved | Reviewer | ☐ |

---

## Compliance Officer Sign-Off

> The following attestations must be confirmed by the Compliance Officer before merging to `main`.

| Attestation | Compliance Officer | Date |
|---|---|---|
| I confirm the 7-year encounter retention policy is correctly enforced by the archival job | ______________ | ________ |
| I confirm the 6-year audit log retention policy is correctly enforced by the purge job | ______________ | ________ |
| I confirm no audit log row can be purged before its Cloud Storage copy is confirmed (WORM) | ______________ | ________ |
| I confirm the Cloud Monitoring alert meets the 5-minute failure notification SLA | ______________ | ________ |

---

## Merge Gate

This task is **blocking** — no code from TASK-001 through TASK-005 may merge to `main` until:

1. All checklist items above are marked ✓
2. The Compliance Officer Sign-Off table is fully signed
3. The `test_cron_jobs_registered` test passes on Cloud SQL dev (CI gate: `SMARTHANDOFF_INTEGRATION_CLOUD_SQL=true`)
4. `terraform plan` shows zero unexpected changes for all three environments (dev/staging/prod)
