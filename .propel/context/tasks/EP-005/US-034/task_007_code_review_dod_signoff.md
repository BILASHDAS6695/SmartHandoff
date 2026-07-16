---
id: TASK-007
title: "Code Review and Definition of Done Sign-Off — US-034"
user_story: US-034
epic: EP-005
sprint: 2
layer: Cross-cutting
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-034/TASK-001, US-034/TASK-002, US-034/TASK-003, US-034/TASK-004, US-034/TASK-005, US-034/TASK-006]
---

# TASK-007: Code Review and Definition of Done Sign-Off — US-034

> **Story:** US-034 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Cross-cutting | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

All implementation tasks (TASK-001 through TASK-006) must be reviewed and signed off against the US-034 Definition of Done before the story transitions to `Done`.

This task acts as the final gate. Run `/review-code` on all changed files and verify each DoD item.

---

## Acceptance Criteria Addressed

| Requirement | Verification |
|---|---|
| All 4 US-034 AC Scenarios | Verified by unit tests (TASK-006) and code inspection |
| DoD: `sla_escalation_sent_at` column | Migration applied; column present in `agent_task` |
| DoD: Escalation to `notification-requests` | `ChargePharmacistEscalationPublisher` publishes with `priority=HIGH` |
| DoD: Override endpoint + RBAC | Endpoint exists; RBAC enforced; unit tests pass |
| DoD: Unit tests pass | `pytest -q` exits 0 |
| DoD: Code reviewed and approved | This task — peer review sign-off |

---

## Review Checklist

### Schema and Migration (TASK-001)

- [ ] `sla_escalation_sent_at` column is `nullable=True`, `DateTime(timezone=True)` — not a non-nullable default
- [ ] Alembic migration has both `upgrade()` and `downgrade()` — downgrade drops column and index
- [ ] Partial index `ix_agent_task_medrec_sla_pending` created for monitor poll query efficiency
- [ ] No other columns removed or modified — surgical change only

### SLA Config (TASK-002)

- [ ] `MEDICATION_RECONCILIATION_ADMISSION` entry in `sla_config.yaml` with `threshold_minutes=1440`, `reference_field=admit_time`, `escalation_type=CHARGE_PHARMACIST_ESCALATION`, `priority=HIGH`
- [ ] `reference_field` defaults to `"created_at"` — existing entries unaffected
- [ ] `med_reconciliation_admission_entry()` accessor raises `KeyError` on missing config (not silent `None`)

### SLA Monitor (TASK-003)

- [ ] `MedRecSLAMonitor` registered as **second job** (`id="medrec_sla_check"`) on the **same `AsyncIOScheduler`** — not a new scheduler instance
- [ ] Poll query filters `agent_type='MEDICATION_RECONCILIATION'`, `status IN ('IN_PROGRESS','PENDING')`, `sla_escalation_sent_at IS NULL`
- [ ] SLA window measured from `encounter.admit_time` — **not** `AgentTask.created_at`
- [ ] `sla_escalation_sent_at` stamped **before** `publisher.publish()` call
- [ ] `COMPLETED` tasks excluded from escalation
- [ ] Log statements contain only non-PHI fields: `encounter_id`, `task_id`, `hours_elapsed`, `patient_unit`

### Publisher (TASK-004)

- [ ] `ChargePharmacistEscalationPayload` has `notification_type="CHARGE_PHARMACIST_ESCALATION"`, `priority="HIGH"`, `encounter_id`, `task_id`, `patient_unit`, `hours_elapsed`, `sent_at`
- [ ] `priority="HIGH"` set as **Pub/Sub message attribute** (not only in JSON payload body)
- [ ] `future.result(timeout=10)` — synchronous result call with timeout
- [ ] No PHI in log output

### Override Endpoint (TASK-005)

- [ ] `PATCH /api/v1/encounters/{encounter_id}/tasks/{task_id}/override` registered and returns HTTP 200 on success
- [ ] `AgentTask.status = COMPLETED`, `completed_at = NOW()`, `sla_escalation_sent_at = None`
- [ ] `AuditLog` record written with `action="TASK_MANUALLY_OVERRIDDEN"`, `actor_id`, `note`
- [ ] HTTP 403 for roles outside `{charge_pharmacist, pharmacy_supervisor}`
- [ ] HTTP 404 if task not found or encounter mismatch
- [ ] HTTP 409 if already `COMPLETED`
- [ ] HTTP 422 if task is not `MEDICATION_RECONCILIATION` type
- [ ] OpenAPI metadata complete: `summary`, `description`, `tags`, response codes

### Unit Tests (TASK-006)

- [ ] All 9 test functions present and passing
- [ ] No live DB, Pub/Sub, or network I/O — all external dependencies mocked
- [ ] `pytest -q` in both `sla-monitor/` and `backend/` exits with 0 failures
- [ ] No `time.sleep()` or real `datetime.now()` without patching in time-sensitive tests

### Security

- [ ] No PHI (patient name, MRN, DOB, phone, email) logged anywhere in new code
- [ ] RBAC enforced at dependency level (`require_roles`) — not only in handler logic
- [ ] `note` field max length 500 enforced by Pydantic — prevents oversized audit log entries

---

## Sign-Off

| Reviewer | Role | Date | Status |
|---|---|---|---|
| | Backend Engineer | | ☐ Pending |
| | Tech Lead | | ☐ Pending |
