---
id: TASK-006
title: "Code Review & DoD Sign-off — US-038 ED Boarding Alert"
user_story: US-038
epic: EP-006
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-038/TASK-001, US-038/TASK-002, US-038/TASK-003, US-038/TASK-004, US-038/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-038 ED Boarding Alert

> **Story:** US-038 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-038. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is required** for this story due to two risk surfaces:

### 1. PHI containment in Pub/Sub alert payload (HIPAA / BR-020, AIR-040)

The `BoardingAlertPayload` is published to `notification-requests` — a shared topic read by the Notification Service. Confirm:

- **`BoardingAlertPayload`** contains only: `notification_type`, `priority`, `patient_id` (opaque UUID — not MRN), `encounter_id` (opaque UUID), `ed_arrival_time` (ISO-8601 UTC), `minutes_elapsed` (integer), `target_unit` (unit code string), `idempotency_key`.
- **No PHI fields** — `first_name`, `last_name`, `dob`, `mrn`, `phone`, `email` must not appear in the payload, Pub/Sub message attributes, or structured logs.
- **`BoardingMonitor` logs** include only `encounter_id` (UUID), `minutes_elapsed`, `current_location` (code) — no patient identifiers beyond the opaque encounter UUID.
- **`boarding_alert_sent_at` / `boarding_alert_resolved_at`** are timestamp columns only — no PHI persisted in the new columns.
- Confirm that Cloud Logging log sink excludes any field named `mrn`, `first_name`, `last_name`, `dob` (belt-and-suspenders, consistent with US-035 TASK-007).

### 2. Idempotency and exactly-once delivery (correctness / patient safety)

Duplicate boarding alerts to the bed manager create alert fatigue and erode trust in the system. Confirm:

- **In-memory check**: `candidate.already_alerted` (fast path) is evaluated before any Pub/Sub call.
- **DB-level guard**: `UPDATE encounter SET boarding_alert_sent_at = now WHERE boarding_alert_sent_at IS NULL` — atomic under concurrent `bed-mgmt-agent` Cloud Run instances.
- **Pub/Sub failure recovery**: if `future.result()` raises, `boarding_alert_sent_at` is NOT written — the next 5-minute cycle retries cleanly.
- **Monitor exclusion**: encounters with `boarding_alert_resolved_at IS NOT NULL` are excluded from detection — resolved alerts never retrigger.
- **`idempotency_key`** in Pub/Sub message attributes enables Notification Service to deduplicate at its layer (AIR-040 downstream).

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# -----------------------------------------------------------------------
# 1. Linting and SAST
# -----------------------------------------------------------------------
cd backend
ruff check app/agents/bed_management/boarding_monitor.py \
           app/agents/bed_management/boarding_publisher.py \
           app/agents/bed_management/boarding_resolver.py \
           app/agents/bed_management/boarding_schemas.py \
           app/agents/bed_management/ed_location_loader.py

bandit -r app/agents/bed_management/ -ll

cd api-gateway
ruff check app/routers/beds.py
bandit -r app/routers/beds.py -ll

# -----------------------------------------------------------------------
# 2. Unit tests with coverage
# -----------------------------------------------------------------------
cd backend
pytest tests/unit/agents/bed_management/test_boarding_monitor.py \
       tests/unit/agents/bed_management/test_boarding_publisher.py \
       tests/unit/agents/bed_management/test_boarding_resolver.py \
       -v --cov=app/agents/bed_management/boarding_monitor \
          --cov=app/agents/bed_management/boarding_publisher \
          --cov=app/agents/bed_management/boarding_resolver \
       --cov-report=term-missing \
       --cov-fail-under=80

# -----------------------------------------------------------------------
# 3. Database migration validation
# -----------------------------------------------------------------------
cd backend
alembic upgrade head
psql "$DATABASE_URL" -c "\d encounter" | grep boarding
# Expected:
#  boarding_alert_sent_at     | timestamp with time zone |
#  boarding_alert_resolved_at | timestamp with time zone |

alembic downgrade -1  # verify rollback
alembic upgrade head  # reapply

# -----------------------------------------------------------------------
# 4. Container build — no CRITICAL CVEs
# -----------------------------------------------------------------------
docker build -t smarthandoff/bed-mgmt-agent:us038 backend/
docker build -t smarthandoff/api-gateway:us038 api-gateway/

# -----------------------------------------------------------------------
# 5. Manual smoke test — boarding monitor cycle (staging)
# -----------------------------------------------------------------------
# Insert a test encounter with admit_time = now - 125 minutes, location=ED,
# bed_assigned_at=NULL, then trigger one scheduler cycle and verify:
# (a) notification-requests message received with priority=IMMEDIATE
# (b) encounter.boarding_alert_sent_at is set
# (c) Running cycle again does NOT publish a second message

# 6. Manual smoke test — resolution (staging)
curl -s -X PATCH \
  -H "Authorization: Bearer $STAGING_BED_MANAGER_JWT" \
  -H "Content-Type: application/json" \
  -d '{"new_status":"RESERVED","encounter_id":"'$TEST_ENCOUNTER_ID'"}' \
  "https://api.staging.smarthandoff.internal/api/v1/beds/$TEST_BED_ID/status" | jq .

# Verify encounter.boarding_alert_resolved_at is set in DB:
psql "$DATABASE_URL" -c \
  "SELECT boarding_alert_resolved_at FROM encounter WHERE id = '$TEST_ENCOUNTER_ID'"
```

---

## Definition of Done Checklist

Map to US-038 DoD items:

- [ ] `BoardingMonitor` checks encounters with `current_location` in ED codes and no `bed_assigned_at` more than 120 minutes old
- [ ] Alert published to `notification-requests` with `priority=IMMEDIATE` and boarding-specific payload (`patient_id`, `ed_arrival_time`, `minutes_elapsed`, `target_unit`, `idempotency_key`)
- [ ] `boarding_alert_sent_at` field added to `encounter` via Alembic migration (TASK-001)
- [ ] `boarding_alert_sent_at` written after successful Pub/Sub publish (TASK-003)
- [ ] Alert idempotency: second monitor cycle does not republish (TASK-003 in-memory + DB guard)
- [ ] Alert resolution: `boarding_alert_resolved_at` set when bed manager assigns bed via `PATCH /api/v1/beds/{id}/status` (TASK-004)
- [ ] After resolution, `BoardingMonitor` no longer detects the encounter (TASK-002 `WHERE boarding_alert_resolved_at IS NULL`)
- [ ] Boarding monitor APScheduler interval: 5 minutes (TASK-002)
- [ ] ED location codes loaded from `config/ed_locations.yaml` (TASK-001 + TASK-002)
- [ ] Unit tests pass: threshold detection, no-alert before threshold, idempotency, resolution (TASK-005, coverage ≥80%)
- [ ] Linting (ruff), SAST (bandit) pass on all new modules
- [ ] Container builds successfully with no CRITICAL CVEs
- [ ] Code peer-reviewed and approved

---

## Reviewer Checklist

For the peer reviewer conducting the code review:

### Correctness
- [ ] `BOARDING_THRESHOLD_MINUTES = 120` constant used consistently — no magic numbers
- [ ] COALESCE(`admit_time`, `transfer_time`) handles both A01 admissions and ED-originating transfers correctly
- [ ] `_run_cycle()` exception handler catches broadly but logs the full traceback
- [ ] `boarding_alert_sent_at` DB update uses atomic `WHERE boarding_alert_sent_at IS NULL`
- [ ] `resolve_boarding_alert()` called before `session.commit()` — same transaction as bed status update

### Security
- [ ] `BoardingAlertPayload` Pydantic model reviewed field-by-field — no PHI
- [ ] `patient_id` is an opaque UUID (not MRN, not name) in all logs and payloads
- [ ] `PATCH /api/v1/beds/{id}/status` endpoint still requires `BedManager` or `Admin` role after TASK-004 modification
- [ ] No secrets or credentials in `config/ed_locations.yaml`

### Observability
- [ ] `BoardingMonitor` logs include `encounter_id` (UUID) and `minutes_elapsed` at `INFO` level when alert fires
- [ ] `BoardingAlertPublisher` logs `message_id` from Pub/Sub on success
- [ ] `BoardingAlertResolver` logs resolution with `encounter_id` and timestamp at `INFO` level
- [ ] All exception paths log at `ERROR`/`EXCEPTION` level with full traceback

### Operational Safety
- [ ] `BoardingMonitor.register()` uses `replace_existing=True` — safe on service restart
- [ ] APScheduler `misfire_grace_time=60` — missed cycles due to cold start are tolerated
- [ ] ED location codes YAML validated at load time (non-empty); malformed YAML raises at startup
