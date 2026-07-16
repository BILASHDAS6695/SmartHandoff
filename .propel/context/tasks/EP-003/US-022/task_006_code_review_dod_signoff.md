---
id: TASK-006
title: "Code Review and Definition of Done Sign-off for US-022"
user_story: US-022
epic: EP-003
sprint: 2
layer: QA / Review
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Tech Lead
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Code Review and Definition of Done Sign-off for US-022

> **Story:** US-022 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** QA / Review | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task gates the merge of US-022 work. It ensures all DoD items are satisfied before the branch is merged to `build/development`. The reviewer verifies functional correctness, security, latency compliance, group routing integrity, and test coverage — not code style (handled by pre-commit linting and CI).

---

## Definition of Done Review Checklist

### Functionality

- [ ] **TASK-001** — `POST /api/v1/signalr/task-updated` is registered in FastAPI; `SignalRBroadcaster` sends POST to `encounter-{id}`, `unit-{unitId}`, and `role-{roleName}` groups via Azure SignalR REST API; `PyJWT` generates a valid HS256 bearer token for each broadcast call
- [ ] **TASK-002** — `POST /api/v1/signalr/negotiate` is registered in FastAPI; `GroupResolver.resolve()` returns correct group names for nurse (unit-bound) and pharmacist (role-only) personas; negotiate endpoint returns `{ url, accessToken }` for authenticated users
- [ ] **TASK-003** — `TaskStatusTransitionService.transition()` calls `db.commit()` before `broadcaster.broadcast_task_updated()`; `unit_id` and `target_role` columns present on `AgentTask` model; Alembic migration `upgrade()` / `downgrade()` succeed cleanly; `update_task_status` in shared agent base lib delegates to `TaskStatusTransitionService`
- [ ] **TASK-004** — Angular `SignalRService` uses `HubConnectionBuilder` with `accessTokenFactory` and `withAutomaticReconnect(RECONNECT_DELAYS_MS)`; `taskUpdated$` Observable emits `TaskUpdatedEvent`; `onreconnected` handler calls `encounterTasksApi.getTasksForEncounter()`; `DashboardComponent` subscribes on `ngOnInit` and unsubscribes on `ngOnDestroy`
- [ ] **TASK-005** — Integration test `test_broadcast_called_within_1_second_of_db_commit` passes; elapsed time logged in test output is < 1.0s; Scenario 2 isolation tests confirm unit-4B group absent from unit-3A nurse's group list

### Security

- [ ] `POST /api/v1/signalr/task-updated` — secured by `get_current_internal_service` (service-to-service JWT, internal ingress only); not accessible from public internet via Cloud Armor rules
- [ ] `POST /api/v1/signalr/negotiate` — secured by `get_current_staff_user`; returns `401` without a valid JWT (confirmed by `curl` smoke test in TASK-002 validation loop)
- [ ] `AZURE_SIGNALR_CONNECTION_STRING` — sourced from GCP Secret Manager; not hardcoded or committed to repository; Secret Manager Terraform resource created (TASK-002)
- [ ] No PHI fields (patient name, MRN, DOB, diagnosis) appear in any SignalR group names, event payloads, or JWT claims

### Schema Integrity

- [ ] Alembic migration adds `unit_id` (VARCHAR 20) and `target_role` (VARCHAR 50) to `agent_task` table
- [ ] `downgrade()` removes both columns without errors on a clean test DB
- [ ] Existing `AgentTask` rows receive `server_default` values during upgrade (no NOT NULL violation)

### Group Routing Correctness

- [ ] Unit test `test_nurse_3a_does_not_join_unit_4b` passes (US-022 Scenario 2 isolation)
- [ ] Unit test `test_pharmacist_without_unit_has_no_unit_group` passes
- [ ] Integration test `test_unit_3a_nurse_not_in_unit_4b_group` passes

### Test Coverage

- [ ] `pytest backend/tests/unit/signalr/ -v` — all unit tests pass (broadcaster, group resolver, task status service)
- [ ] `pytest backend/tests/integration/signalr/ -v -m integration` — all integration tests pass (requires test DB)
- [ ] `npx jest src/app/core/signalr/signalr.service.spec.ts --coverage` — Angular service tests pass; coverage ≥80% on `signalr.service.ts`
- [ ] No test makes a live Azure SignalR, GCP Pub/Sub, or production DB call

### Latency Compliance

- [ ] Integration test confirms broadcast is initiated < 1.0 second after `db.commit()` (US-022 Scenario 1, NFR-006, TR-003)
- [ ] `withAutomaticReconnect` configured with retry delays `[0, 1000, 2000, 5000]` ms — first retry at 0ms, reconnect within 5s achievable (US-022 Scenario 3)

### Observability

- [ ] `SignalRBroadcaster.broadcast_task_updated()` logs `INFO` with `task_id`, `group`, `new_status` on success
- [ ] Broadcast HTTP errors logged as `WARNING` — no unhandled exceptions propagate to agent task flow
- [ ] `SignalRService` (Angular) logs reconnect events — no `console.error` on normal reconnect cycle

### Cloud Run Configuration

- [ ] FastAPI backend Cloud Run service has `min-instances=2` set (TR-003 — SignalR hub latency requirement)
- [ ] Cloud Run ingress for `POST /api/v1/signalr/task-updated` is restricted to `internal` traffic only (agents are co-located in same VPC)
- [ ] `--timeout=3600` confirmed in Cloud Run configuration for long-lived WebSocket connections (US-022 Technical Notes)

---

## Sign-off

| Reviewer | Role | Date | Status |
|---|---|---|---|
| | Tech Lead | | ☐ Approved / ☐ Changes Required |
| | Backend Engineer | | ☐ Self-reviewed |
| | AI/ML Engineer | | ☐ Self-reviewed |
