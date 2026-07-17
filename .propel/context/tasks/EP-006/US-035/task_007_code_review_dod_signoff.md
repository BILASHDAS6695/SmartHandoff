---
id: TASK-007
title: "Code Review & DoD Sign-off — US-035 Real-Time Bed Availability Board"
user_story: US-035
epic: EP-006
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-035/TASK-001, US-035/TASK-002, US-035/TASK-003, US-035/TASK-004, US-035/TASK-005, US-035/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-035 Real-Time Bed Availability Board

> **Story:** US-035 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-035. It verifies that all implementation tasks (TASK-001 through TASK-006) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to three high-risk surfaces:

### 1. PHI containment in logs and Pub/Sub payloads (HIPAA / BR-020)

The BedManagementAgent processes ADT events linked to encounters that contain PHI. Confirm:

- **`BedManagementAgent` logs** include only `encounter_id` (UUID), `event_type`, `bed_id` — no patient name, MRN, DOB, or any other PHI field.
- **`HousekeepingNotificationPayload`** contains only `bed_id`, `unit`, `room`, `bed_number`, `encounter_id`, `idempotency_key`, `notification_type` — no PHI.
- **`GET /api/v1/beds` response** returns only bed coordinates and status — no patient identifiers linking a specific patient to a bed.
- **`PATCH /api/v1/beds/{id}/status` audit event** stores `user_id`, `bed_id`, previous/new status, and reason — no PHI.
- **`BedInventorySeeder` logs** include only row counts and file paths — no PHI.
- Confirm that Cloud Logging log sink is configured to exclude any field named `mrn`, `first_name`, `last_name`, `dob` (belt-and-suspenders).

### 2. Materialised view CONCURRENTLY refresh safety (correctness / patient safety)

A stale bed board can cause placement errors. Confirm:

- `uix_mv_bed_board_bed_id` unique index exists on `mv_bed_board` (required for `CONCURRENTLY`).
- `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_bed_board` is executed on the **primary** DB, not the read replica.
- `BedBoardRefreshService._do_refresh()` catches and logs exceptions without re-raising, so a failed refresh does not crash the agent.
- pg_cron 60-second scheduled refresh (US-009) remains as baseline if an event-driven refresh fails.

### 3. RBAC enforcement on PATCH endpoint (authorisation / BR-021)

- `PATCH /api/v1/beds/{id}/status` returns HTTP 403 for any role other than `BedManager` and `Admin`.
- `GET /api/v1/beds` requires at least one of: `Admin`, `BedManager`, `Physician`, `Nurse` — a `Patient` JWT must return 403.
- Confirm that `require_role()` dependency is applied at the router level, not just in the handler body.

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
    # bed-mgmt-agent service
    'backend/app/agents/bed_management/__init__.py',
    'backend/app/agents/bed_management/schemas.py',
    'backend/app/agents/bed_management/status_machine.py',
    'backend/app/agents/bed_management/agent.py',
    'backend/app/agents/bed_management/refresh_service.py',
    'backend/app/agents/bed_management/seeder.py',
    'backend/app/agents/bed_management/notifier.py',
    'backend/app/agents/bed_management/main.py',
    # api-gateway
    'api-gateway/app/routers/beds.py',
]
for p in targets:
    ast.parse(pathlib.Path(p).read_text())
    print(f'  {p}: OK')
print('Syntax check: PASSED')
"

# -----------------------------------------------------------------------
# 2. Status machine smoke test
# -----------------------------------------------------------------------
cd backend
python -c "
from app.agents.bed_management.schemas import BedStatus
from app.agents.bed_management.status_machine import resolve_target_status
from app.exceptions import BedStatusTransitionError

# Valid transitions
assert resolve_target_status('A01', BedStatus.VACANT) == BedStatus.OCCUPIED, 'A01 VACANT→OCCUPIED failed'
assert resolve_target_status('A01', BedStatus.DIRTY) == BedStatus.OCCUPIED, 'A01 DIRTY→OCCUPIED failed'
assert resolve_target_status('A03', BedStatus.OCCUPIED) == BedStatus.DIRTY, 'A03 OCCUPIED→DIRTY failed'
assert resolve_target_status('A02', BedStatus.VACANT) == BedStatus.OCCUPIED, 'A02 new bed VACANT→OCCUPIED failed'

# Invalid transition guard
try:
    resolve_target_status('A03', BedStatus.VACANT)
    assert False, 'Expected BedStatusTransitionError for A03 on VACANT'
except BedStatusTransitionError:
    pass

# Unknown event guard
try:
    resolve_target_status('A08', BedStatus.VACANT)
    assert False, 'Expected ValueError for unhandled A08'
except ValueError:
    pass

print('Status machine smoke test: PASSED')
"

# -----------------------------------------------------------------------
# 3. Run unit test suite
# -----------------------------------------------------------------------
cd backend
pytest tests/unit/agents/bed_management/ -v --cov=app/agents/bed_management \
    --cov-report=term-missing --cov-fail-under=80

cd ../api-gateway
pytest tests/unit/routers/test_beds_router.py -v --cov=app/routers/beds \
    --cov-report=term-missing --cov-fail-under=80

# -----------------------------------------------------------------------
# 4. Alembic migration check
# -----------------------------------------------------------------------
cd ../backend
alembic upgrade head          # apply unique index migration
alembic downgrade -1          # verify reversibility
alembic upgrade head          # re-apply

# -----------------------------------------------------------------------
# 5. Seeder idempotency smoke test (against staging DB)
# -----------------------------------------------------------------------
python -c "
import asyncio
from app.agents.bed_management.seeder import BedInventorySeeder
from app.agents.bed_management.refresh_service import BedBoardRefreshService
from app.core.dependencies import get_write_db

async def run():
    refresh_service = BedBoardRefreshService(write_session_factory=get_write_db)
    seeder = BedInventorySeeder(
        session_factory=get_write_db,
        refresh_service=refresh_service,
    )
    first_run = await seeder.seed()
    print(f'First run inserted: {first_run}')
    second_run = await seeder.seed()
    print(f'Second run inserted (expect 0): {second_run}')
    assert second_run == 0, 'Seeder is NOT idempotent!'
    print('Seeder idempotency: PASSED')

asyncio.run(run())
"

# -----------------------------------------------------------------------
# 6. Static analysis
# -----------------------------------------------------------------------
ruff check backend/app/agents/bed_management/ api-gateway/app/routers/beds.py
bandit -r backend/app/agents/bed_management/ api-gateway/app/routers/beds.py -ll
```

---

## Definition of Done Checklist

### Functional
- [ ] `BedManagementAgent` extends `BaseAgent`; processes A01 (→OCCUPIED), A02 (old→DIRTY, new→OCCUPIED), A03 (→DIRTY)
- [ ] `bed` ORM table with: `unit`, `room`, `bed_number`, `bed_type`, `status`, `isolation_required`, `gender_designation` (confirmed present via US-006 migration)
- [ ] `mv_bed_board` materialised view `CONCURRENTLY` refresh triggered after each bed status change
- [ ] Unique index `uix_mv_bed_board_bed_id` confirmed on `mv_bed_board`
- [ ] Bed inventory seeding: idempotent `INSERT ... ON CONFLICT DO NOTHING` from `config/bed_inventory.yaml`
- [ ] Housekeeping Pub/Sub notification: `notification-requests` topic within 5 seconds of A03
- [ ] `GET /api/v1/beds` endpoint with `unit`, `status`, `bed_type` filters; routes to read replica
- [ ] `PATCH /api/v1/beds/{id}/status` endpoint with BedManager RBAC; audit event emitted

### Testing
- [ ] Unit tests: all 4 AC scenarios covered
- [ ] Unit tests: ≥80% branch coverage on all modules
- [ ] `pytest` exits with code 0 (no failures)

### Non-Functional
- [ ] No PHI in logs, Pub/Sub payloads, or API responses
- [ ] `REFRESH MATERIALIZED VIEW CONCURRENTLY` runs on primary DB
- [ ] PATCH requires BedManager or Admin role; 403 for all other roles
- [ ] Alembic migration reversible (`downgrade -1` tested)
- [ ] `bandit` SAST: zero HIGH severity findings in new modules

### Process
- [ ] Pull request opened with description referencing US-035
- [ ] At least one peer code review approval
- [ ] Security Engineer sign-off on PHI containment and RBAC sections
- [ ] All review comments resolved before merge

---

## Reviewer Checklist

| Area | Reviewer | Sign-off |
|------|----------|----------|
| Bed status state machine logic | Backend Engineer | ☐ |
| PHI containment in logs & Pub/Sub payloads | Security Engineer | ☐ |
| RBAC enforcement (GET and PATCH endpoints) | Security Engineer | ☐ |
| Alembic migration reversibility | Backend Engineer | ☐ |
| Seeder idempotency | Backend Engineer | ☐ |
| Unit test coverage ≥80% | Backend Engineer | ☐ |
| Housekeeping notification 5-second SLA | Backend Engineer | ☐ |
