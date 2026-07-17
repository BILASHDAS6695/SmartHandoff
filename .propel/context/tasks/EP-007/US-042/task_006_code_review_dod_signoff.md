---
id: TASK-006
title: "Code Review & DoD Sign-off — US-042 Escalate Post-Discharge Urgent Concerns Within 15 Minutes"
user_story: US-042
epic: EP-007
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-042/TASK-001, US-042/TASK-002, US-042/TASK-003, US-042/TASK-004, US-042/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-042 Escalate Post-Discharge Urgent Concerns Within 15 Minutes

> **Story:** US-042 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-042. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to three high-risk surfaces:

### 1. RBAC enforcement on the acknowledgement endpoint (SEC-002 / design.md §8.3)

The `PATCH /api/v1/care/escalations/{id}/acknowledge` endpoint grants write access to clinical escalation state. A misconfigured `require_any_role` dependency could allow patients to suppress escalation alerts.

Verify:
- `require_any_role({"admin", "physician", "nurse", "charge_nurse"})` is applied as a FastAPI **dependency** at the router level — not as an inline `if` check inside the handler.
- Patient JWT (roles `["patient"]`) returns `403 Forbidden` — confirmed by `test_patient_jwt_returns_403`.
- Pharmacist JWT (roles `["pharmacist"]`) returns `403 Forbidden` — confirmed by `test_pharmacist_jwt_returns_403`.
- The `acknowledged_by` field is set from `current_user["sub"]` (JWT `sub` claim) — not from a request body parameter, which would allow impersonation.
- `acknowledged_by` is a UUID FK to `app_user.id` — the JWT `sub` claim must be validated to reference a real `app_user` record (or raise 401) by the auth middleware upstream.

### 2. PHI containment in Pub/Sub messages and logs (HIPAA / BR-020, ADR-007)

The escalation pipeline publishes two Pub/Sub messages (`CARE_TEAM_ESCALATION` and `SUPERVISOR_ESCALATION`) and writes multiple log lines. PHI must not appear in either.

Confirm for each published message body:
- Contains only UUIDs (`escalation_id`, `encounter_id`, `patient_id`, `nurse_user_id`) and metadata fields.
- Does NOT contain: `first_name`, `last_name`, `mrn`, `dob`, `phone`, `email`.

Confirm for each log line emitted by `monitor.py`, `reescalation_job.py`, and `care_escalations.py` router:
- Contains only `escalation_id` (UUID), `encounter_id` (UUID), `nurse_user_id` / `acknowledged_by` (UUID).
- Does NOT contain: patient name, MRN, DOB, phone, or email.
- Confirm Cloud Logging sink excludes any field named `mrn`, `first_name`, `last_name`, `dob` from the `followup-agent` log sink.

### 3. Escalation SLA integrity (patient safety)

A 15-minute SLA breach without a supervisor notification could result in a medical emergency going unresponded to.

Verify:
- `ReEscalationJob.run()` uses `sent_at < NOW() - INTERVAL '15 minutes'` as the SLA cutoff — not `created_at` and not `urgency_flag_set_at`.
- The APScheduler job runs every **60 seconds** with `misfire_grace_time=30` — confirm in scheduler registration.
- The DB UPDATE in `_reescalate()` uses `WHERE status=PENDING AND escalated_to_supervisor=FALSE` to prevent concurrent duplicate supervisor notifications.
- The `NOTIF-SUP-ESC-{escalation_id}` idempotency key on the Notification Service prevents duplicate SMS even if the Pub/Sub message is delivered twice.
- `sent_at` is set in `CareEscalationMonitor._get_or_create_escalation()` as `datetime.now(tz=timezone.utc)` — it records when the **notification was dispatched**, not when the urgency flag was set. This is correct per US-042 Technical Notes.

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# -----------------------------------------------------------------------
# 1. Syntax check — all new modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
targets = [
    'backend/app/models/care_escalation.py',
    'backend/app/agents/followup_care/escalation/__init__.py',
    'backend/app/agents/followup_care/escalation/schemas.py',
    'backend/app/agents/followup_care/escalation/monitor.py',
    'backend/app/agents/followup_care/escalation/reescalation_job.py',
    'api-gateway/app/schemas/care_escalation.py',
    'api-gateway/app/routers/care_escalations.py',
]
for t in targets:
    p = pathlib.Path(t)
    if p.exists():
        ast.parse(p.read_text())
        print(f'OK: {t}')
    else:
        print(f'MISSING: {t}')
"

# -----------------------------------------------------------------------
# 2. Ruff lint
# -----------------------------------------------------------------------
ruff check backend/app/models/care_escalation.py \
    backend/app/agents/followup_care/escalation/ \
    api-gateway/app/schemas/care_escalation.py \
    api-gateway/app/routers/care_escalations.py

# -----------------------------------------------------------------------
# 3. Bandit SAST (security scan)
# -----------------------------------------------------------------------
bandit -r backend/app/agents/followup_care/escalation/ \
         api-gateway/app/routers/care_escalations.py \
         -ll -ii

# -----------------------------------------------------------------------
# 4. Unit tests with coverage
# -----------------------------------------------------------------------
pytest backend/tests/unit/agents/followup_care/escalation/ \
       api-gateway/tests/unit/routers/test_acknowledge_router.py \
       -v --cov=backend/app/agents/followup_care/escalation \
       --cov=api-gateway/app/routers/care_escalations \
       --cov-report=term-missing \
       --cov-fail-under=80

# -----------------------------------------------------------------------
# 5. Alembic migration integrity check
# -----------------------------------------------------------------------
cd backend && alembic check
# Expected: "No new upgrade operations detected." (migration already applied)

# -----------------------------------------------------------------------
# 6. PHI log audit — confirm no PHI fields in module source
# -----------------------------------------------------------------------
grep -rn "first_name\|last_name\|mrn\|\.dob\|\.phone\|\.email" \
    backend/app/agents/followup_care/escalation/ \
    api-gateway/app/routers/care_escalations.py
# Expected: zero matches (only ORM model references are acceptable — not log calls)
```

---

## Code Review Checklist

### Security (Security Engineer)

- [ ] `require_any_role` dependency applied at router level (not inline `if` in handler)
- [ ] `acknowledged_by` sourced from `current_user["sub"]` JWT claim — not from request body
- [ ] `CARE_TEAM_ESCALATION` Pub/Sub payload contains no PHI fields
- [ ] `SUPERVISOR_ESCALATION` Pub/Sub payload contains no PHI fields
- [ ] `monitor.py` log lines contain no PHI fields
- [ ] `reescalation_job.py` log lines contain no PHI fields
- [ ] `care_escalations.py` router log lines contain no PHI fields
- [ ] Bandit scan: no HIGH severity findings

### Data Integrity (Backend Engineer)

- [ ] `care_escalation.idempotency_key` unique constraint prevents duplicate escalation records
- [ ] `ReEscalationJob` UPDATE uses `WHERE status=PENDING AND escalated_to_supervisor=FALSE` (concurrent-safe)
- [ ] `sent_at` set from `datetime.now(tz=timezone.utc)` in monitor — timezone-aware
- [ ] `NOTIF-ESC-{escalation_id}` and `NOTIF-SUP-ESC-{escalation_id}` idempotency keys distinct
- [ ] Alembic migration autogenerated (no raw SQL); `deleted_at` column present

### SLA Compliance (Backend Engineer)

- [ ] APScheduler job interval = 60 seconds; `misfire_grace_time=30`
- [ ] SLA cutoff uses `care_escalation.sent_at` (not `urgency_flag_set_at`)
- [ ] No synchronous FHIR API calls on the 60-second SLA critical path in `monitor.py`

### Test Coverage (Backend Engineer)

- [ ] All 4 AC scenarios covered by unit tests
- [ ] ≥80% branch coverage on `monitor.py`, `reescalation_job.py`, `care_escalations.py` router
- [ ] PHI check assertion in `test_urgency_flag_publishes_care_team_escalation` and `test_reescalation_publishes_supervisor_escalation`
- [ ] `app.dependency_overrides.clear()` called in all router test teardowns

---

## US-042 Definition of Done — Final Sign-off

- [ ] **TASK-001**: `care_escalation` ORM model + Alembic migration applied to dev
- [ ] **TASK-002**: `CareEscalationMonitor` processes `URGENCY_FLAG_SET`; publishes `CARE_TEAM_ESCALATION` within 60 s
- [ ] **TASK-003**: APScheduler re-escalation job publishes `SUPERVISOR_ESCALATION` after 15-minute SLA breach
- [ ] **TASK-004**: `PATCH /api/v1/care/escalations/{id}/acknowledge` endpoint with RBAC; 403/404/409 handled
- [ ] **TASK-005**: 14 unit tests passing; ≥80% coverage
- [ ] **TASK-006**: Code review completed; security sign-off granted
- [ ] No PHI in Pub/Sub payloads or log lines
- [ ] No hardcoded credentials — all secrets via GCP Secret Manager (SEC-011)
