---
id: TASK-005
title: "Code Review & DoD Sign-off — US-041 48-Hour Post-Discharge Check-In Scheduling"
user_story: US-041
epic: EP-007
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-041/TASK-001, US-041/TASK-002, US-041/TASK-003, US-041/TASK-004]
---

# TASK-005: Code Review & DoD Sign-off — US-041 48-Hour Post-Discharge Check-In Scheduling

> **Story:** US-041 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-041. It verifies that TASK-001 through TASK-004 are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to three PHI-sensitive surfaces:

### 1. PHI in Notification Dispatch (HIPAA / BR-020, AIR-021)

The 48-hour check-in message includes `patient.first_name` in the message body. Confirm:

- **`checkin_scheduler.py` logs** — include only `encounter_id` (UUID), `risk_score`, `send_at`, `channel`. No `patient.first_name`, `phone`, `email`, `mrn`, or `dob` in any log field.
- **`scheduled_dispatcher.py` logs** — `notification_sent` and `notification_opted_out` entries contain only `scheduled_notification_id` (UUID) and `encounter_id` (UUID). No PHI in any log statement.
- **`sms_service.py`** and **`email_service.py`** — confirm `first_name` and `to_phone`/`to_email` are used only as function arguments passed to the Twilio/SendGrid SDK. They are NOT logged, not written to structured logs, and not included in exception messages.
- **`scheduled_notification` table** — confirm no phone number, email address, or patient name is stored. The table contains only UUIDs (`patient_id`, `encounter_id`) and non-PHI operational fields (`send_at`, `channel`, `delivery_status`). PHI is resolved at dispatch time from the encrypted `patient` record.
- Confirm Cloud Logging for `notification-svc` and `followup-agent` log sinks are configured to exclude fields named `first_name`, `phone`, `email`, `mrn`, `dob`.

### 2. Idempotency Integrity (ADR-001 — at-least-once delivery)

Pub/Sub guarantees at-least-once delivery. A03 messages may be redelivered after transient failures.

- Confirm `idempotency_key = f"CHK48-{encounter_id}"` is unique per encounter (not per invocation timestamp).
- Confirm `flush()` exception handling in `maybe_schedule_48h_checkin()` catches the PostgreSQL `UniqueViolation` and calls `session.rollback()` before returning `None`.
- Confirm the Alembic migration defines `uq_scheduled_notification_idempotency_key` unique constraint — this is the DB-level safeguard, not just an application-level check.
- Confirm the test `test_returns_none_on_unique_constraint_violation` covers this path.

### 3. Risk Threshold Correctness (Patient Safety)

An incorrect threshold would schedule check-ins for LOW risk patients (wasted resource) or miss MEDIUM risk patients (patient safety gap).

- Confirm `CHECKIN_RISK_THRESHOLD = 0.5` is defined in exactly **one** location: `checkin_scheduler.py`. It must not be duplicated in `agent.py`, the migration, or any test fixture.
- Confirm the boundary tests in `test_checkin_scheduler.py` cover: `risk_score < 0.5` (no schedule), `risk_score == 0.5` (schedule), `risk_score > 0.5` (schedule).
- Confirm the threshold is not the same as the US-039 risk tier boundaries (`LOW < 0.30`, `MEDIUM 0.30–0.70`, `HIGH ≥ 0.70`) — the 0.5 check-in threshold is distinct and intentional.

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# ───────────────────────────────────────────────────────────────────────
# 1. Syntax check — all new modules
# ───────────────────────────────────────────────────────────────────────
python -c "
import ast, pathlib
targets = [
    'backend/app/models/scheduled_notification.py',
    'backend/app/agents/followup_care/checkin_scheduler.py',
    'notification-service/app/scheduled_dispatcher.py',
    'notification-service/app/services/sms_service.py',
    'notification-service/app/services/email_service.py',
]
for t in targets:
    ast.parse(pathlib.Path(t).read_text())
    print(f'OK: {t}')
"

# ───────────────────────────────────────────────────────────────────────
# 2. Type checking
# ───────────────────────────────────────────────────────────────────────
mypy backend/app/models/scheduled_notification.py \
     backend/app/agents/followup_care/checkin_scheduler.py \
     --strict

mypy notification-service/app/scheduled_dispatcher.py \
     notification-service/app/services/sms_service.py \
     notification-service/app/services/email_service.py \
     --strict

# ───────────────────────────────────────────────────────────────────────
# 3. Linting
# ───────────────────────────────────────────────────────────────────────
ruff check backend/app/models/scheduled_notification.py \
           backend/app/agents/followup_care/checkin_scheduler.py \
           notification-service/app/scheduled_dispatcher.py \
           notification-service/app/services/

bandit -r backend/app/agents/followup_care/checkin_scheduler.py \
          notification-service/app/scheduled_dispatcher.py \
          notification-service/app/services/

# ───────────────────────────────────────────────────────────────────────
# 4. Unit tests with coverage
# ───────────────────────────────────────────────────────────────────────
pytest backend/tests/unit/agents/followup_care/test_checkin_scheduler.py -v

pytest notification-service/tests/unit/test_scheduled_dispatcher.py -v

pytest --cov=app.agents.followup_care.checkin_scheduler \
       --cov=app.scheduled_dispatcher \
       --cov-fail-under=80 \
       --cov-report=term-missing

# ───────────────────────────────────────────────────────────────────────
# 5. Alembic migration round-trip
# ───────────────────────────────────────────────────────────────────────
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head

# Verify table exists and has expected columns
psql $DATABASE_URL -c "
    SELECT column_name, data_type, is_nullable
    FROM   information_schema.columns
    WHERE  table_name = 'scheduled_notification'
    ORDER  BY ordinal_position;
"

# Verify unique constraint
psql $DATABASE_URL -c "
    SELECT conname FROM pg_constraint
    WHERE  conrelid = 'scheduled_notification'::regclass
    AND    contype = 'u';
"
```

---

## Definition of Done Checklist

| DoD Item | Verification |
|---|---|
| `ScheduledNotification` ORM model: `type`, `send_at`, `patient_id`, `encounter_id`, `channel`, `delivery_status` | `backend/app/models/scheduled_notification.py` reviewed ✓ |
| Follow-up care agent creates `CHECK_IN_48H` record for `risk_score ≥ 0.5` | `checkin_scheduler.py` + integration test passing ✓ |
| Notification service reads scheduled notifications from DB and dispatches at `send_at` time | `scheduled_dispatcher.py` polling every 5 min ✓ |
| Opt-out flag respected: `patient.notification_opt_out=True` → skip + log | `test_opted_out_patient_*` tests passing ✓ |
| Unit tests: schedule creation for correct risk thresholds, opt-out enforcement | 20 tests passing, ≥80% coverage ✓ |
| Code reviewed and approved | Sign-off from Security Engineer below ✓ |

---

## Review Sign-off

| Reviewer | Role | Date | Outcome |
|---|---|---|---|
| _TBD_ | Backend Engineer (peer) | _TBD_ | ☐ Approved / ☐ Changes Required |
| _TBD_ | Security Engineer | _TBD_ | ☐ Approved / ☐ Changes Required |

**Security Engineer sign-off is required before this story is marked DONE.**

---

## Files Reviewed

| File | Change Type |
|---|---|
| `backend/app/models/scheduled_notification.py` | New |
| `backend/app/models/__init__.py` | Modified |
| `backend/app/migrations/versions/0012_add_scheduled_notification.py` | New |
| `backend/app/agents/followup_care/checkin_scheduler.py` | New |
| `backend/app/agents/followup_care/agent.py` | Modified |
| `backend/app/agents/followup_care/schemas.py` | Modified |
| `notification-service/app/scheduled_dispatcher.py` | New |
| `notification-service/app/services/sms_service.py` | New |
| `notification-service/app/services/email_service.py` | New |
| `notification-service/app/main.py` | Modified |
| `notification-service/app/config.py` | Modified |
| `backend/tests/unit/agents/followup_care/test_checkin_scheduler.py` | New |
| `notification-service/tests/unit/test_scheduled_dispatcher.py` | New |
