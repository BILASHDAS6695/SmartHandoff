---
id: TASK-006
title: "Code Review & DoD Sign-off — US-058 Audit Trail Implementation"
user_story: US-058
epic: EP-011
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-058/TASK-001, US-058/TASK-002, US-058/TASK-003, US-058/TASK-004, US-058/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-058 Audit Trail Implementation

> **Story:** US-058 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-058. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are met, and both a peer code review and a Security Engineer sign-off have been completed.

The Security Engineer review is required by the US-058 DoD: *"Code reviewed and Security Engineer reviewed"*.

---

## Pre-Review Checklist

Run the full validation sequence before requesting review:

```bash
cd backend

# 1. Install dependencies
pip install -r requirements.txt

# 2. Confirm AuditLog ORM model imports cleanly
python -c "from app.models.audit_log import AuditLog, AuditAction; print('Model: OK', list(AuditAction))"

# 3. Confirm write helpers import cleanly
python -c "from app.db.audit import write_audit_entry, write_rbac_audit_entry; print('Audit helpers: OK')"

# 4. Confirm PHI sanitiser imports and redact_phi works
python -c "
from app.middleware.phi_log_sanitiser import redact_phi
result = redact_phi('{\"first_name\": \"Alice\", \"email\": \"alice@test.com\"}')
assert 'Alice' not in result
assert '[REDACTED]' in result
print('PHI sanitiser: OK')
"

# 5. Run US-058 unit tests with coverage
pytest tests/unit/middleware/test_audit_log_middleware.py \
       tests/unit/middleware/test_phi_log_sanitiser.py \
       tests/unit/routers/test_admin_audit.py \
       -v --tb=short \
       --cov=app/middleware/audit_log_middleware \
       --cov=app/middleware/phi_log_sanitiser \
       --cov=app/routers/admin/audit \
       --cov=app/db/audit \
       --cov-report=term-missing \
       --cov-fail-under=80

# 6. Run full unit test suite — confirm no regressions from new middleware
pytest tests/unit/ -q

# 7. Confirm PHI field names absent from Cloud Logging stream
# Run a test request and grep stdout for any PHI value
python -m pytest tests/unit/middleware/test_phi_log_sanitiser.py \
  -v -s 2>&1 | grep -E "(Alice|Bob|MRN|@hospital)" | wc -l
# Expected output: 0 (no PHI in log output)

# 8. Bandit SAST scan — no HIGH or CRITICAL in audit modules
bandit -r backend/app/middleware/audit_log_middleware.py \
          backend/app/middleware/phi_log_sanitiser.py \
          backend/app/db/audit.py \
          backend/app/routers/admin/audit.py -ll
# Expected: No issues identified
```

---

## Code Review Checklist

### Security Review (Security Engineer Required)

- [ ] **No PHI in audit_log:** `AuditLog` ORM model contains no PHI field columns (no `first_name`, `last_name`, `mrn`, etc.) — only `entity_type`, `entity_id`, `user_id`, `action`
- [ ] **No PHI in log messages:** `PhiLoggingFilter` registered on root logger before any handlers emit — verified by test asserting zero PHI in log output
- [ ] **Audit write uses `audit_writer` DB role:** `AUDIT_DB_URL` env var connects with `audit_writer` credentials (INSERT-only on `audit_log`) — not `app_write`
- [ ] **`AuditAction.APPROVE` / `REJECT` correctness:** Action enum covers all DoD-required actions; no free-text action values can be inserted
- [ ] **IP extraction safety:** `X-Forwarded-For` parsing validates each candidate with `ip_address()` before accepting — no injection via malformed XFF header
- [ ] **Audit failure non-blocking:** `write_audit_entry()` absorbs all exceptions; no audit failure propagates to HTTP response (availability over audit, per HIPAA guidance)
- [ ] **Admin query RBAC:** `GET /api/v1/admin/audit` enforces `require_permission("audit_log", "read")` — non-ADMIN roles receive 403 without resource detail disclosure
- [ ] **Regex patterns in `phi_log_sanitiser`:** Compiled at module load (not per-call) — no regex DoS (ReDoS) exposure from unbounded backtracking in email/phone patterns
- [ ] **Read replica for audit query:** `get_read_db_session()` used in admin query endpoint — not the write primary connection

### Functional Review (Peer Engineer)

- [ ] `AuditLogMiddleware` correctly excludes `/api/v1/auth/*`, `/health`, `/ready`, `/metrics`, `/docs`, `/hubs`, `/webhooks`
- [ ] All PHI entity path prefixes from design.md §3.3 covered: patients, encounters, documents, medications, alerts, beds, tasks, admin/audit, admin/users
- [ ] `entity_type` extraction correctly singularises plural path segments (`patients` → `PATIENT`, `documents` → `DOCUMENT`)
- [ ] Middleware stack ordering confirmed in `main.py`: JWT (pos 4) → RBAC (pos 5) → `PhiLogSanitiserMiddleware` (pos 6) → `AuditLogMiddleware` (pos 7)
- [ ] `PhiLoggingFilter` added to root logger AND all existing handlers — not just one handler
- [ ] `GET /api/v1/admin/audit` pagination: `page_size` max capped at 200; page 0 or negative returns 422
- [ ] Alembic migration committed; `alembic upgrade head` succeeds on clean dev DB
- [ ] No hardcoded DB credentials — all connection strings sourced from GCP Secret Manager env vars

### Performance Review

- [ ] `PhiLoggingFilter.filter()` operates in O(n) string operations — no database calls or I/O in the hot log path
- [ ] `AuditLogMiddleware` DB write is non-blocking (async, fire-and-forget) — does not add to response latency
- [ ] Audit query uses indexed columns: `timestamp` (for range queries), `entity_type`, `user_id` — confirm indexes exist in migration

---

## Definition of Done — Final Sign-off

| DoD Item | Owner | Status |
|---|---|---|
| `AuditLogMiddleware`: logs every `/api/v1/` PHI path request | Backend Engineer | ☐ |
| `audit_log` ORM model: all 8 required fields present | Backend Engineer | ☐ |
| PHI sanitiser middleware: strips `first_name`, `last_name`, `mrn`, `dob`, `phone`, `email` from log messages | Backend Engineer | ☐ |
| `GET /api/v1/admin/audit` paginated endpoint — ADMIN role only | Backend Engineer | ☐ |
| IP extraction: `X-Forwarded-For` header supported (Cloud Run proxy-aware) | Backend Engineer | ☐ |
| Unit tests: audit entry creation, PHI sanitisation, admin query RBAC | Backend Engineer | ☐ |
| Code reviewed (peer) | Backend Engineer | ☐ |
| Security Engineer reviewed | Security Engineer | ☐ |

---

## Post-Review Actions

After all checklist items are marked complete and both reviewers have signed off:

1. Merge the feature branch to `main`.
2. Verify Cloud Build pipeline passes all steps (lint → unit tests → container scan → integration tests).
3. Confirm Cloud Deploy canary (10% traffic) shows no increased error rate on `/api/v1/` endpoints.
4. Confirm Cloud Logging shows zero PHI field values in any structured log entry (spot-check 10 recent access logs).
5. Mark US-058 status as `Done` in the sprint board.
