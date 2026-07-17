---
id: TASK-006
title: "Code Review & DoD Sign-off — US-040 High-Risk Care Pathway Activation"
user_story: US-040
epic: EP-007
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-040/TASK-001, US-040/TASK-002, US-040/TASK-003, US-040/TASK-004, US-040/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-040 High-Risk Care Pathway Activation

> **Story:** US-040 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-040. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to two high-risk surfaces:

---

### 1. PHI exposure risk in appointment records and Pub/Sub alert payload (HIPAA / BR-020, AIR-021)

The `appointment` table and `CARE_MANAGER_ALERT` Pub/Sub message must never expose PHI.

**Review checklist:**

- `appointment` table columns: `encounter_id` (UUID), `appointment_type`, `target_date`, `status`, `assigned_user_id` — confirm no PHI fields (no patient name, MRN, DOB, phone, email).
- `CarePathwayService` logs: confirm only `encounter_id` (UUID), `risk_tier`, `appointment_type`, `target_date`, `assigned_user_id` (UUID) appear — never `mrn`, `first_name`, `last_name`, `dob`.
- `NotificationPublisher` logs: confirm only `encounter_id`, `risk_tier`, `appointment_id`, `pubsub_message_id` — no PHI.
- `CareManagerAlertPayload` JSON published to `notification-requests`: fields are `alert_type`, `encounter_id`, `risk_score`, `risk_tier`, `required_followup_days`, `appointment_id`, `idempotency_key` — no PHI.
- Confirm Cloud Logging sinks for `followup-agent` exclude any field named `mrn`, `first_name`, `last_name`, `dob`.

---

### 2. Pub/Sub publish-after-commit pattern correctness (data integrity / patient safety)

Sending a `CARE_MANAGER_ALERT` for a patient whose `appointment` record was rolled back would trigger a care manager to act on a record that doesn't exist in the DB — a patient safety risk.

**Review checklist:**

- Confirm `db.commit()` is called **before** `notification_publisher.publish_care_manager_alert()` in `agent.py`.
- Confirm there is no `await db.commit()` inside the `activate_pathway()` method — the `CarePathwayService` should only `flush()`, not `commit()`. The commit is owned by the agent to ensure atomicity.
- Confirm that if `publish_care_manager_alert()` raises a `GoogleAPIError`, the agent:
  - Logs the error at `ERROR` level with `encounter_id` and `appointment_id`
  - Does **not** rollback the committed DB record (appointment is already persisted)
  - Does **not** `nack()` the Pub/Sub A03 message (the appointment is already created; re-processing would cause a duplicate `UniqueConstraintViolation`)
  - Flags the alert as `PENDING_RETRY` via a separate retry mechanism (or logs for manual resolution — acceptable in Phase 1)

---

### 3. Idempotency on Pub/Sub redelivery (AIR-040)

If the `followup-agent-sub` Pub/Sub subscription redelivers the A03 event:
- `CarePathwayService.activate_pathway()` will attempt to insert an `appointment` row that already exists → `UniqueConstraintViolation` on `uq_appointment_encounter_type`.
- Confirm the agent catches `sqlalchemy.exc.IntegrityError` on the duplicate and **skips** re-processing (idempotent guard) without re-publishing the alert.
- Confirm the `idempotency_key` attribute on the Pub/Sub `CARE_MANAGER_ALERT` message prevents the Notification Service from sending a duplicate SMS/email (AIR-040).

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# 1. All unit tests pass
cd backend
pytest tests/unit/config/test_care_pathways_config.py \
       tests/unit/services/test_care_pathway_service.py \
       tests/unit/agents/followup_care/test_followup_agent_us040.py \
       -v --tb=short

# 2. Coverage ≥80% on new modules
pytest tests/unit/config/test_care_pathways_config.py \
       tests/unit/services/test_care_pathway_service.py \
       tests/unit/agents/followup_care/test_followup_agent_us040.py \
       --cov=app/config/care_pathways \
       --cov=app/services/care_pathway_service \
       --cov=app/agents/followup_care/notification_publisher \
       --cov-report=term-missing \
       --cov-fail-under=80

# 3. Static analysis — no issues in new files
ruff check backend/app/models/appointment.py \
            backend/app/config/care_pathways.py \
            backend/app/services/care_pathway_service.py \
            backend/app/agents/followup_care/notification_publisher.py

# 4. SAST — no bandit HIGH/MEDIUM findings in new files
bandit -r backend/app/services/care_pathway_service.py \
           backend/app/agents/followup_care/notification_publisher.py \
           -ll

# 5. Alembic migration: clean apply + downgrade + re-apply
alembic upgrade head
alembic current   # expect: 0007 (head)
alembic downgrade -1
alembic upgrade head

# 6. Confirm no PHI in log fields (grep for forbidden field names in new source files)
grep -rn "mrn\|first_name\|last_name\|\.dob" \
     backend/app/services/care_pathway_service.py \
     backend/app/agents/followup_care/notification_publisher.py \
     backend/app/models/appointment.py
# Expected output: zero matches
```

---

## DoD Verification Checklist

### US-040 Definition of Done

- [ ] `FollowUpCareAgent.process()` activates care pathway after risk score calculation
- [ ] Care manager alert: `POST` to `notification-requests` Pub/Sub for HIGH tier only
- [ ] Appointment record creation for all 3 tiers (different `target_date` and `type`)
- [ ] `appointment` ORM table: `encounter_id`, `appointment_type`, `target_date`, `status`, `assigned_user_id`
- [ ] Risk tier-to-pathway mapping in `config/care_pathways.yaml` (configurable follow-up days)
- [ ] Unit tests: HIGH/MEDIUM/LOW tier pathway logic, appointment creation, alert firing condition
- [ ] Code reviewed and approved

### Task Completion Verification

| Task | Module | Reviewer Verified |
|------|--------|-------------------|
| TASK-001 | `backend/app/models/appointment.py` | [ ] |
| TASK-001 | `backend/alembic/versions/0007_add_appointment_table.py` | [ ] |
| TASK-002 | `backend/config/care_pathways.yaml` | [ ] |
| TASK-002 | `backend/app/config/care_pathways.py` | [ ] |
| TASK-003 | `backend/app/services/care_pathway_service.py` | [ ] |
| TASK-004 | `backend/app/agents/followup_care/notification_publisher.py` | [ ] |
| TASK-004 | `CareManagerAlertPayload` in `schemas.py` | [ ] |
| TASK-004 | `FollowUpCareAgent.process()` extension in `agent.py` | [ ] |
| TASK-005 | `test_care_pathways_config.py` (13 tests) | [ ] |
| TASK-005 | `test_care_pathway_service.py` (10 tests) | [ ] |
| TASK-005 | `test_followup_agent_us040.py` (8 tests) | [ ] |

### Security Sign-off

| Security Concern | Verified By | Status |
|-----------------|-------------|--------|
| No PHI in appointment table columns | Security Engineer | [ ] |
| No PHI in CarePathwayService logs | Security Engineer | [ ] |
| No PHI in CARE_MANAGER_ALERT Pub/Sub payload | Security Engineer | [ ] |
| Publish-after-commit order confirmed | Security Engineer | [ ] |
| Idempotency guard on Pub/Sub redelivery | Security Engineer | [ ] |
| `UniqueConstraintViolation` caught and handled idempotently | Security Engineer | [ ] |

---

## Reviewer Sign-off

| Role | Name | Date | Approved |
|------|------|------|----------|
| Peer Reviewer | | | [ ] |
| Security Engineer | | | [ ] |
| Tech Lead | | | [ ] |
