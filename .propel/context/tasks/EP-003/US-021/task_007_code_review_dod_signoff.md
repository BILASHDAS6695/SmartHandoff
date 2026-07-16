---
id: TASK-007
title: "Code Review and Definition of Done Sign-off for US-021"
user_story: US-021
epic: EP-003
sprint: 2
layer: QA / Review
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Tech Lead
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006]
---

# TASK-007: Code Review and Definition of Done Sign-off for US-021

> **Story:** US-021 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** QA / Review | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task gates the merge of US-021 work. It ensures all DoD items are satisfied before the branch is merged to `build/development`. The reviewer verifies functional correctness, security, schema integrity, and test coverage — not code style (handled by pre-commit linting).

---

## Definition of Done Review Checklist

### Functionality

- [ ] **TASK-001** — `sla_config.yaml` present; `load_sla_config()` returns a valid `SLAConfig`; per-agent thresholds match US-021 Technical Notes
- [ ] **TASK-002** — `AgentTask` ORM model has `sla_threshold_minutes` and `sla_breached` columns; Alembic migration `upgrade()` / `downgrade()` are clean; partial index present
- [ ] **TASK-003** — `SLAMonitor` uses `APScheduler AsyncIOScheduler`; `time.sleep()` is absent; monitor polls using `get_read_session()`; writes `sla_breached = True` using `get_write_session()`; `max_instances=1` on scheduled job
- [ ] **TASK-004** — `EscalationPublisher.publish()` sends payload with all 6 required fields (`notification_type`, `encounter_id`, `agent_type`, `minutes_elapsed`, `supervisor_id`, `fired_at`); idempotency guard prevents duplicate messages within dedup window; failed publishes do not mark key as sent
- [ ] **TASK-005** — `GET /api/v1/encounters/{id}/tasks` returns `200` with all 7 AC fields; `sla_threshold_minutes` backfilled from `SLAConfig` when DB column is `NULL`; `404` for unknown encounter; `401` without JWT

### Security

- [ ] JWT authentication enforced on `GET /api/v1/encounters/{id}/tasks` via `get_current_staff_user` dependency
- [ ] No PHI fields (patient names, MRN, DOB) exposed in `AgentTaskResponse` schema
- [ ] No secrets hardcoded in any configuration file; GCP project ID sourced from environment variable

### Schema Integrity

- [ ] Alembic `downgrade()` removes both new columns and the partial index cleanly on a clean dev DB
- [ ] Existing `AgentTask` rows default `sla_breached = false` after migration (server default confirmed)

### Test Coverage

- [ ] All 18 unit tests pass: `pytest sla-monitor/tests/unit/ -v`
- [ ] `test_find_breached_tasks_excludes_completed` specifically validates US-021 Scenario 3
- [ ] `test_bed_management_threshold_is_15_minutes` specifically validates US-021 Scenario 4
- [ ] No test makes a live DB or Pub/Sub call

### Observability

- [ ] SLA breach events logged at `INFO` level with `task_id`, `agent_type`, `elapsed`, `threshold`
- [ ] Suppressed (dedup) escalations logged at `DEBUG` level
- [ ] Monitor start/stop logged at `INFO` level

### Infrastructure

- [ ] `notification-requests` Pub/Sub topic declared in Terraform (`infra/terraform/modules/pubsub/main.tf`) with DLQ subscription

---

## Review Instructions

1. Run `/review-code` on all files introduced by TASK-001 through TASK-006.
2. Run `pytest sla-monitor/tests/unit/ -v` and confirm all 18 tests pass.
3. Apply the Alembic migration on a clean dev DB and verify `SELECT * FROM agent_task LIMIT 1` shows `sla_breached = false`.
4. Confirm `sla_config.yaml` does not contain hardcoded project IDs or secrets.
5. Verify `GET /api/v1/encounters/{id}/tasks` returns `401` when called without an `Authorization` header.
6. Mark each DoD checkbox above and approve the PR when all items are confirmed.

---

## Files Reviewed

| Path | Introduced By |
|---|---|
| `sla-monitor/app/config/sla_config.yaml` | TASK-001 |
| `sla-monitor/app/config/sla_loader.py` | TASK-001 |
| `sla-monitor/tests/unit/test_sla_loader.py` | TASK-001 |
| `backend/app/models/agent_task.py` | TASK-002 |
| `backend/alembic/versions/<rev>_add_sla_columns_to_agent_task.py` | TASK-002 |
| `sla-monitor/app/monitor/sla_monitor.py` | TASK-003 |
| `sla-monitor/app/db/session.py` | TASK-003 |
| `sla-monitor/app/main.py` | TASK-003 |
| `sla-monitor/app/publisher/escalation_publisher.py` | TASK-004 |
| `infra/terraform/modules/pubsub/main.tf` | TASK-004 |
| `backend/app/schemas/agent_task.py` | TASK-005 |
| `backend/app/routers/encounter_tasks.py` | TASK-005 |
| `backend/app/main.py` | TASK-005 |
| `sla-monitor/tests/unit/test_sla_monitor.py` | TASK-006 |
| `sla-monitor/tests/unit/test_escalation_publisher.py` | TASK-006 |
