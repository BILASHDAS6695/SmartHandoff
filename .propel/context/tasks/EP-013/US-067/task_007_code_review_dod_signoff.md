---
id: TASK-007
title: "Code Review & Definition of Done Sign-Off for US-067 — Notification Audit Log API with Patient Opt-Out Support"
user_story: US-067
epic: EP-013
sprint: 2
layer: Process
estimate: 0.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006]
---

# TASK-007: Code Review & Definition of Done Sign-Off for US-067 — Notification Audit Log API with Patient Opt-Out Support

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Process | **Est:** 0.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task is the final gate for US-067. It verifies all Definition of Done (DoD) items are complete before the story is marked `Done` and the PR is merged to the `build/development` branch.

Must be executed after TASK-001 through TASK-006 are complete and all unit tests are passing.

---

## Definition of Done Checklist

### API Endpoints

- [ ] **`GET /api/v1/notifications?encounter_id={id}`** implemented in `backend/app/routers/notifications.py`
  - [ ] Staff JWT required (`NURSE`, `PHYSICIAN`, `CARE_COORDINATOR`, `ADMIN`)
  - [ ] Query routes to PostgreSQL read replica via `get_read_db` dependency
  - [ ] Response includes: `type`, `channel`, `sent_at`, `delivery_status`, `template_name`, `urgency_override`
  - [ ] No PHI in response (`recipient_phone`, `recipient_email` absent; only `_hash` variants returned)
  - [ ] Returns `200` with empty list if no notifications found (no `404`)
  - [ ] `encounter_id` required parameter; missing parameter returns `422`

- [ ] **`PATCH /api/v1/portal/preferences`** implemented in `backend/app/routers/portal_preferences.py`
  - [ ] Patient JWT required (`get_current_patient_user` dependency)
  - [ ] Staff JWT rejected (`403 Forbidden`)
  - [ ] `notification_opt_out` persisted to `patient` table on primary DB
  - [ ] `urgency_override` absent from request schema (security constraint)
  - [ ] Returns `200 OK` with `{"notification_opt_out": <bool>}` body
  - [ ] Audit log entry created on preference change (BR-012)

### Notification Service — Opt-Out Logic

- [ ] **Opt-out gate** implemented in `notification-service/app/dispatcher.py`
  - [ ] `if patient.notification_opt_out and not msg.urgency_override: skip()`
  - [ ] `OPTED_OUT` notification record created when suppressed (no dispatch)
  - [ ] `urgency_override=True` bypasses opt-out and records `urgency_override=True` on notification
  - [ ] Patient opt-out read from write primary DB (not read replica)
  - [ ] Audit log written for every dispatch attempt (BR-012): `NOTIFICATION_DISPATCHED`, `NOTIFICATION_SUPPRESSED_OPT_OUT`, `NOTIFICATION_FAILED`

### Pub/Sub Schema

- [ ] **`urgency_override: bool = False`** added to `NotificationMessage` in `notification-service/app/schemas/notification_message.py`
  - [ ] Default `False` ensures backward compatibility with existing publishers
  - [ ] Urgent publishers set `urgency_override=True` in message payload
  - [ ] Field not settable via `PATCH /api/v1/portal/preferences`

### Database Schema

- [ ] **`notification` table** updated (Alembic migration committed and applied)
  - [ ] `delivery_status` enum includes `OPTED_OUT` value
  - [ ] `urgency_override BOOLEAN NOT NULL DEFAULT FALSE` column added

- [ ] **`patient` table** updated (Alembic migration committed and applied)
  - [ ] `notification_opt_out BOOLEAN NOT NULL DEFAULT FALSE` column added

### PHI Minimisation

- [ ] `recipient_phone` and `recipient_email` (plaintext) absent from `GET /api/v1/notifications` response
- [ ] Only `recipient_phone_hash` and `recipient_email_hash` (SHA-256) returned in response
- [ ] No patient name, DOB, or MRN in any notification log response field
- [ ] `patient_id` UUID (not name) used in audit log entries

### Security

- [ ] `urgency_override` is not settable by patient portal endpoint
- [ ] Staff JWT rejected from `PATCH /api/v1/portal/preferences` (RBAC boundary maintained)
- [ ] Patient JWT rejected from `GET /api/v1/notifications` (staff-only endpoint)
- [ ] No secrets, API keys, or PHI in committed code

### Unit Tests

- [ ] `notification-service/tests/test_dispatcher_optout.py` — all tests pass:
  - [ ] `test_opt_out_suppression_creates_opted_out_record`
  - [ ] `test_urgency_bypass_dispatches_despite_opt_out`
  - [ ] `test_opted_in_patient_receives_non_urgent_notification`
- [ ] `backend/tests/test_portal_preferences.py` — all tests pass:
  - [ ] `test_patient_preference_update_sets_opt_out_true`
  - [ ] `test_patient_preference_update_sets_opt_out_false`
  - [ ] `test_urgency_override_not_in_request_schema`
  - [ ] `test_staff_jwt_rejected_from_portal_preferences`
- [ ] `backend/tests/test_notifications_audit_log.py` — all tests pass:
  - [ ] `test_staff_log_query_returns_correct_fields`
  - [ ] `test_phi_excluded_from_notification_log_response`
  - [ ] `test_empty_list_returned_for_encounter_with_no_notifications`
  - [ ] `test_encounter_id_required_parameter`
- [ ] No regressions in existing US-064 notification service tests

### Quality Gates

```bash
# Run full US-067 test suite
cd notification-service && pytest tests/test_dispatcher_optout.py -v
cd ../backend && pytest tests/test_portal_preferences.py tests/test_notifications_audit_log.py -v

# Syntax checks
cd notification-service
python -c "import ast, pathlib; [ast.parse(pathlib.Path(f).read_text()) for f in ['app/dispatcher.py', 'app/schemas/notification_message.py']]"
cd ../backend
python -c "import ast, pathlib; [ast.parse(pathlib.Path(f).read_text()) for f in ['app/routers/notifications.py', 'app/routers/portal_preferences.py', 'app/schemas/notification_log.py', 'app/schemas/portal.py']]"

# Alembic migration status
cd notification-service && alembic current
cd ../backend && alembic current
```

### Code Review

- [ ] PR opened against `build/development` branch
- [ ] Reviewer confirmed `urgency_override` is not patient-settable
- [ ] Reviewer confirmed PHI minimisation: no plaintext phone/email in audit log response
- [ ] Reviewer confirmed opt-out reads from write primary (not replica)
- [ ] Reviewer confirmed audit log written for every notification attempt (BR-012)
- [ ] Reviewer confirmed all four DoD unit test categories present and passing
- [ ] PR approved and merged

---

## Files Involved (Full US-067 Deliverable Surface)

| File | Task | Role |
|------|------|------|
| `notification-service/app/models/notification.py` | TASK-001 | `urgency_override` column + `OPTED_OUT` enum |
| `notification-service/app/migrations/versions/<rev>_us067_*.py` | TASK-001 | Alembic migration for notification table |
| `backend/app/models/patient.py` | TASK-001 | `notification_opt_out` column |
| `backend/app/migrations/versions/<rev>_us067_*.py` | TASK-001 | Alembic migration for patient table |
| `notification-service/app/schemas/notification_message.py` | TASK-002 | `urgency_override` field on `NotificationMessage` |
| `notification-service/app/dispatcher.py` | TASK-003 | Opt-out gate + urgency bypass + audit log |
| `backend/app/schemas/notification_log.py` | TASK-004 | `NotificationLogItem` + `NotificationLogResponse` |
| `backend/app/routers/notifications.py` | TASK-004 | `GET /api/v1/notifications` router |
| `backend/app/schemas/portal.py` | TASK-005 | `PortalPreferencesUpdateRequest` + response schema |
| `backend/app/routers/portal_preferences.py` | TASK-005 | `PATCH /api/v1/portal/preferences` router |
| `backend/app/main.py` | TASK-004, TASK-005 | Router registration |
| `notification-service/tests/test_dispatcher_optout.py` | TASK-006 | Opt-out suppression + urgency bypass tests |
| `backend/tests/test_portal_preferences.py` | TASK-006 | Patient preference update tests |
| `backend/tests/test_notifications_audit_log.py` | TASK-006 | Staff log query tests + PHI guard |
