---
id: TASK-006
title: "Code Review & DoD Sign-off — US-045 Care Team Escalation & Acknowledgement"
user_story: US-045
epic: EP-008
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-045/TASK-001, US-045/TASK-002, US-045/TASK-003, US-045/TASK-004, US-045/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-045 Care Team Escalation & Acknowledgement

> **Story:** US-045 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-045. It verifies that TASK-001 through TASK-005 are complete, all Definition of Done items are satisfied, and a peer code review (Security Engineer co-review) has been completed.

A **Security Engineer review is mandatory** for this story because it introduces three high-risk surfaces:

### 1. Patient scope enforcement on escalation write (HIPAA / SEC-002 / US-045 AC Scenario 4)

The `_enforce_encounter_scope()` check in `POST /api/v1/chat/escalate` is the critical control preventing a patient from creating escalations under another patient's encounter — which would allow them to inject notifications to care staff and potentially gain information about other encounters.

**Verify:**
- `_enforce_encounter_scope()` is the **first operation** in the handler — before DB query or Pub/Sub publish
- The 403 response body is `{"detail": "Access denied."}` — no information about whether the target encounter exists
- Unit test `test_post_escalate_wrong_encounter_returns_403` is present and passes (TASK-005)
- There is **no admin bypass** or query parameter that skips the check

### 2. PHI minimisation in Pub/Sub payload and logs (HIPAA / BR-021 / AIR-021)

`EscalationAlertPayload` publishes to Pub/Sub. The `urgency_message_summary` field contains the patient's own words, which may describe symptoms.

**Verify:**
- `EscalationAlertPayload.patient_first_name` contains first name only — no surname, DOB, MRN
- `EscalationAlertPayload.urgency_message_summary` is truncated to 200 characters
- `urgency_message` on the ORM row does NOT appear in any Cloud Logging output (check all log statements in `service.py`, `pubsub_publisher.py`, `routers/escalation.py`)
- `acknowledged_at` and `ack_time_minutes` are logged — they contain no PHI
- No patient-identifiable fields (`first_name`, `urgency_message`) appear in structured log entries at any severity level

### 3. Fire-and-forget Pub/Sub safety (design.md §10.2)

The Pub/Sub publish uses `asyncio.create_task()`. If this coroutine raises an unhandled exception, it may be silently swallowed without logging.

**Verify:**
- `publish_escalation_alert()` has a `try/except Exception` block that logs the error before returning
- The exception is NOT re-raised (fire-and-forget contract maintained)
- Unit test `test_pubsub_published_as_fire_and_forget` confirms `asyncio.create_task` is used — not `await`
- Cloud Monitoring alert exists for `escalation_pubsub_error` log-based metric (Terraform in infra/modules/monitoring/)

---

## Pre-Review Validation Sequence

Run all checks before submitting for peer review:

```bash
# -----------------------------------------------------------------------
# 1. Syntax check — all US-045 modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
modules = [
    'backend/app/agents/patient_comm/escalation/__init__.py',
    'backend/app/agents/patient_comm/escalation/schemas.py',
    'backend/app/agents/patient_comm/escalation/models.py',
    'backend/app/agents/patient_comm/escalation/service.py',
    'backend/app/agents/patient_comm/escalation/pubsub_publisher.py',
    'backend/app/agents/patient_comm/escalation/oncall_resolver.py',
    'backend/app/agents/patient_comm/escalation/monitoring.py',
    'api-gateway/app/routers/escalation.py',
]
for path in modules:
    p = pathlib.Path(path)
    if p.exists():
        ast.parse(p.read_text())
        print(f'OK: {path}')
    else:
        print(f'MISSING: {path}')
"

# -----------------------------------------------------------------------
# 2. Ruff lint — all modules
# -----------------------------------------------------------------------
ruff check backend/app/agents/patient_comm/escalation/ \
           api-gateway/app/routers/escalation.py

# -----------------------------------------------------------------------
# 3. Bandit SAST — escalation module
# -----------------------------------------------------------------------
bandit -r backend/app/agents/patient_comm/escalation/ \
          api-gateway/app/routers/escalation.py \
       -ll --quiet

# -----------------------------------------------------------------------
# 4. Unit tests + coverage
# -----------------------------------------------------------------------
cd backend && pytest tests/unit/agents/patient_comm/escalation/ \
  --cov=backend/app/agents/patient_comm/escalation \
  --cov-fail-under=80 -v

cd ../api-gateway && pytest \
  tests/unit/routers/test_escalation_endpoints_post_patch.py \
  tests/unit/routers/test_escalation_endpoint_get.py \
  --cov=api_gateway/app/routers/escalation \
  --cov-fail-under=80 -v

# -----------------------------------------------------------------------
# 5. Alembic round-trip check
# -----------------------------------------------------------------------
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
echo "Alembic round-trip: PASS"

# -----------------------------------------------------------------------
# 6. Schema column check
# -----------------------------------------------------------------------
psql $DATABASE_URL -c "\d chatbot_escalation"
# Expected columns: id, encounter_id, transcript_message_id, notified_user_id,
#                   notified_at, acknowledged_at, channel, urgency_message, created_at
# Expected index:   ix_chatbot_escalation_encounter_notified
```

---

## DoD Verification Checklist

Map each DoD item from US-045 to the task that delivers it:

| DoD Item | Delivered By | Status |
|----------|-------------|--------|
| `ChatbotEscalation` ORM model: `encounter_id`, `transcript_message_id`, `notified_user_id`, `notified_at`, `acknowledged_at`, `channel` | TASK-001 | [ ] |
| `POST /api/v1/chat/escalate` endpoint: creates escalation record + publishes to Pub/Sub | TASK-002 | [ ] |
| `PATCH /api/v1/chat/escalation/{id}/acknowledge` endpoint (staff-only RBAC) | TASK-003 | [ ] |
| `GET /api/v1/chat/escalations` endpoint: patient-scoped (own encounter only) + staff (all) | TASK-004 | [ ] |
| Escalation acknowledgement time monitored: if >2 min, flag for review (log metric only in Phase 1) | TASK-003 | [ ] |
| Unit tests: escalation creation, acknowledgement, patient scope enforcement | TASK-005 | [ ] |
| Code reviewed and approved | TASK-006 | [ ] |

---

## Security Review Sign-off Checklist

| Security Control | Evidence | Status |
|-----------------|---------|--------|
| `_enforce_encounter_scope()` is FIRST operation in POST handler | Line order in `routers/escalation.py` | [ ] |
| 403 body is `{"detail": "Access denied."}` — no encounter existence info | `routers/escalation.py` + test | [ ] |
| `urgency_message` absent from all log statements | Code review of all US-045 files | [ ] |
| `EscalationAlertPayload.patient_first_name` = first name only (no surname/DOB/MRN) | `schemas.py` + code review | [ ] |
| `urgency_message_summary` truncated to 200 chars before Pub/Sub publish | `schemas.py` model_validator + test | [ ] |
| `publish_escalation_alert` has try/except that logs but doesn't re-raise | `pubsub_publisher.py` | [ ] |
| `asyncio.create_task` used for Pub/Sub (not `await`) | `service.py` + `test_pubsub_published_as_fire_and_forget` | [ ] |
| HIPAA audit event written: `encounter_id` + `escalation_id` + event type — no PHI content | `routers/escalation.py` audit calls | [ ] |
| Staff RBAC enforced on PATCH /acknowledge via `get_current_staff_token` dependency | `routers/escalation.py` + test | [ ] |
| Patient cannot ack → 403 from `get_current_staff_token` | `test_patient_cannot_acknowledge` | [ ] |
| Alembic FKs: `encounter.id`, `chat_transcript.id`, `app_user.id` with RESTRICT | Alembic migration file | [ ] |
| Non-UUID `escalation_id` in PATCH path → 422 before DB query | `routers/escalation.py` + test | [ ] |

---

## Peer Review Assignment

| Reviewer | Role | Focus |
|----------|------|-------|
| Backend Engineer (peer) | General | API correctness, ORM usage, error handling |
| Security Engineer | Security | PHI log inspection, scope enforcement, fire-and-forget safety |

**Review criteria:**
- All pre-review validation checks pass (zero ruff violations, zero bandit HIGH/MEDIUM, ≥80% coverage)
- All DoD items checked
- All security sign-off items checked
- No hardcoded secrets, credentials, or PHI values in test fixtures
- Alembic migration reviewed and round-trip verified

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-045/TASK-001–005 | Tasks | All must be complete before review |
| Security Engineer | Human | Mandatory co-reviewer per policy |
| `ruff`, `bandit`, `pytest-cov` | Tools | Must be available in CI environment |
