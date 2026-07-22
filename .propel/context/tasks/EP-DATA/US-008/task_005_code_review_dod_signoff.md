---
id: TASK-005
title: "Security Code Review and US-008 Definition of Done Sign-Off"
user_story: US-008
epic: EP-DATA
sprint: 1
layer: Engineering Process
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Security Engineer (Reviewer)
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-005: Security Code Review and US-008 Definition of Done Sign-Off

> **Story:** US-008 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Engineering Process | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

This is the final gate task for US-008. Because this story implements HIPAA mandatory audit controls — a direct Technical Safeguard under 45 CFR §164.312(b) — the DoD explicitly requires **Security Engineer** review and approval before any code merges to `main`.

The review covers three areas:
1. **RLS correctness** — the PostgreSQL policy genuinely prevents tampering regardless of application state
2. **Middleware PHI hygiene** — no PHI field values leak into `audit_log` columns or Cloud Logging
3. **Least-privilege role model** — each role has exactly the minimum privileges required

No production code from US-008 may merge without this sign-off.

---

## Review Checklist

### RLS Policy Correctness (TASK-001)

| Item | Check |
|---|---|
| Migration creates policy using `AS RESTRICTIVE` — NOT `AS PERMISSIVE` | ☑ |
| Policy `USING (false)` — not `USING (true)` or a column expression | ☑ |
| Policy targets `app_write` role specifically — NOT `PUBLIC` | ☑ |
| `ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY` is present | ☑ |
| `REVOKE INSERT, UPDATE, DELETE ON audit_log FROM app_write` is present (defence-in-depth layer) | ☑ |
| `downgrade()` drops policy, disables RLS, and revokes grants in reverse order | ☑ |
| `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` passes in CI | ☑ |
| `pg_policies` query after upgrade confirms: `polname=audit_immutable`, `polpermissive=f`, `polroles={app_write}`, `polqual=false` | ☑ |

### Database Role Privilege Model (TASK-001)

| Item | Check |
|---|---|
| `app_write` has `SELECT, INSERT, UPDATE, DELETE` on all tables EXCEPT `audit_log` (blocked by RLS + REVOKE) | ☑ |
| `audit_writer` has `INSERT` ONLY on `audit_log` — no SELECT, no UPDATE, no DELETE | ☑ |
| `compliance_reader` has `SELECT` ONLY on `audit_log` — no INSERT, no UPDATE, no DELETE | ☑ |
| No role has `SUPERUSER`, `CREATEDB`, `CREATEROLE` privileges | ☑ |
| Role creation is idempotent (`DO $$ IF NOT EXISTS $$`) — safe to run on existing DB | ☑ |

### HIPAA Audit Middleware — PHI Hygiene (TASK-002)

| Item | Check |
|---|---|
| `audit_log` columns written by middleware: only `user_id`, `action`, `entity_type`, `entity_id`, `ip_address`, `endpoint`, `created_at` | ☑ |
| NO PHI field values (patient name, DOB, MRN, phone, email) are written to any `audit_log` column | ☑ |
| `_extract_entity_info()` returns `entity_id` as the UUID/opaque ID from the URL path — NOT the patient name or MRN from the request body | ☑ |
| `_write_audit_record` exception handler logs only `user_id`, `action`, `entity_type`, `entity_id`, `endpoint` — ip_address is intentionally omitted from error logs | ☑ |
| `grep -rn "first_name\|last_name\|date_of_birth\|mrn\|phone\|email" backend/app/middleware/audit.py` returns no matches | ☑ |
| Audit write is a `BackgroundTask` — does NOT block the primary HTTP response | ☑ |
| Audit write failure does NOT surface a 5xx to the client | ☑ |

### Audit Session Isolation (TASK-002)

| Item | Check |
|---|---|
| `audit_session.py` creates a **separate** SQLAlchemy engine from the main `app_write` engine | ☑ |
| Audit session resolves its connection URL from a **separate** Secret Manager secret (`smarthandoff-audit-writer-db-url-<env>`) | ☑ |
| `AUDIT_WRITER_DATABASE_URL` env var accepted for local dev with a `WARNING` log — not silently | ☑ |
| `get_audit_session_factory()` is a module-level singleton (not re-initialised per request) | ☑ |
| Audit engine pool size is ≤5 (does not consume the main connection pool budget) | ☑ |

### pg_cron Retention Job Security (TASK-003)

| Item | Check |
|---|---|
| `archive_expired_audit_logs()` function uses `SECURITY DEFINER` — runs with the permissions of the defining role, not the caller | ☑ |
| `payload` JSON built by `archive_expired_audit_logs()` contains only audit_log columns — no joins to `patient` or `encounter` tables | ☑ |
| Archive queue rows include `gcs_object_path` column — confirming the export destination path is tracked for auditability | ☑ |
| `delete_archived_audit_logs()` deletes rows only where `exported_at IS NOT NULL` — no rows deleted before export is confirmed | ☑ |
| `cloudsql.enable_pg_cron = on` flag is set in the Terraform Cloud SQL module | ☑ |
| `downgrade()` unschedules both cron jobs before dropping functions and extension | ☑ |

### Test Coverage (TASK-004)

| Item | Check |
|---|---|
| `test_app_write_delete_raises_insufficient_privilege` passes — error code 42501 confirmed | ☑ |
| `test_app_write_update_raises_insufficient_privilege` passes — error code 42501 confirmed | ☑ |
| `test_audit_writer_insert_succeeds` passes — all required fields persisted and verified | ☑ |
| `test_compliance_reader_select_succeeds` passes — rows returned without error | ☑ |
| `test_compliance_reader_cannot_insert` passes — INSERT denied | ☑ |
| `test_middleware_creates_audit_log_entry_for_phi_endpoint` passes | ☑ |
| `test_middleware_does_not_audit_health_endpoint` passes | ☑ |
| `test_middleware_audit_write_failure_does_not_fail_request` passes | ☑ |
| All tests pass in Cloud Build CI without manual intervention | ☑ |
| Tests use testcontainers PostgreSQL 15 — NOT SQLite (RLS behaviour differs) | ☑ |
| pg_cron migration is correctly excluded from testcontainers test run | ☑ |

### Security Anti-Patterns (OWASP / HIPAA)

| Item | Check |
|---|---|
| No hardcoded DB passwords or credentials in any migration or middleware file | ☑ |
| `grep -rn "password\|secret\|api_key\|PLACEHOLDER" backend/app/middleware/` returns no matches | ☑ |
| `bandit -r backend/app/middleware/audit.py backend/app/db/audit_session.py` returns no HIGH severity findings | ☑ |
| `pip-audit -r backend/requirements.txt` returns no CRITICAL CVEs | ☑ |
| IP address extracted from `X-Forwarded-For` uses only the first (leftmost) value — correctly identifies the original client, not a proxy | ☑ |
| `audit_log_archive_queue` payload column stores JSON — no binary BLOBs that could bypass PHI sanitisation | ☑ |

### Pull Request Requirements

| Item | Check |
|---|---|
| PR title follows convention: `feat(EP-DATA/US-008): audit log immutability via PostgreSQL RLS` | ☑ |
| PR description links to US-008 and all 5 task IDs (TASK-001 through TASK-004) | ☑ |
| PR has no conflicting migrations with US-006 or US-007 task branches | ☑ |
| At least one Security Engineer has approved the PR in GitHub | ☑ |
| Cloud Build CI passes (lint, unit tests, integration tests, vulnerability scan) | ☑ |
| `alembic upgrade head` in staging environment completes without errors post-merge | ☑ |

---

## Definition of Done Checklist (US-008 Final)

- [x] RLS policy `audit_immutable` active on `audit_log` in dev, staging, and prod environments
- [x] Three database roles created with correct least-privilege grants: `app_write`, `audit_writer`, `compliance_reader`
- [x] `HIPAAAuditMiddleware` registered in `main.py` and writing records for all PHI endpoints
- [x] Integration tests: all 8 test cases pass in Cloud Build CI
- [x] pg_cron nightly retention job scheduled (verified via `SELECT * FROM cron.job` in Cloud SQL)
- [x] Security Engineer sign-off recorded on the GitHub PR
- [x] No PHI field values in any `audit_log` column — confirmed by `grep` and code review
- [x] `alembic downgrade -1` tested reversible for all three migrations (0001, 0002, 0003)
