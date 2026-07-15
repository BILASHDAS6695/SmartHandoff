---
id: TASK-009
title: "Code Review and US-006 Definition of Done Sign-Off"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Engineering Process
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Senior Backend Engineer (Reviewer)
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008]
---

# TASK-009: Code Review and US-006 Definition of Done Sign-Off

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Engineering Process | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final gate task for US-006. It validates all preceding tasks are complete, all DoD items are satisfied, and a senior Backend Engineer (ideally with HIPAA/security background) has formally approved the pull request. No code from US-006 may merge to `main` without this sign-off.

The DoD item explicitly requires:

> *"Code reviewed and approved."*

This task covers no code changes — it is a structured review checklist that gates the PR merge.

---

## Acceptance Criteria Addressed

All four scenarios of US-006 are verified end-to-end through the checklist below.

---

## Review Checklist

### Project Structure and Alembic Configuration (TASK-001)

| Item | Check |
|---|---|
| `backend/alembic.ini` exists and contains NO `sqlalchemy.url` entry | ☐ |
| `backend/alembic/env.py` reads `DATABASE_URL` from environment | ☐ |
| `env.py` converts `postgresql://` → `postgresql+asyncpg://` for async engine | ☐ |
| `backend/alembic/versions/` directory exists with at least two migration files | ☐ |
| `grep -n "sqlalchemy.url\|password" backend/alembic.ini` returns zero matches | ☐ |

### ORM Base Infrastructure (TASK-002)

| Item | Check |
|---|---|
| `Base(DeclarativeBase)` defined in `app/db/base.py` with no columns | ☐ |
| `TimestampMixin` uses `server_default=func.now()` and `onupdate=func.now()` (DB-side, not Python-side) | ☐ |
| `SoftDeleteMixin.deleted_at` has `index=True` for query performance | ☐ |
| `SoftDeleteMixin.soft_delete()` sets `deleted_at` to UTC timestamp | ☐ |
| `app/db/session.py` uses `NullPool` (PgBouncer external pooling, TR-009) | ☐ |

### ORM Models — Patient, AppUser, Bed (TASK-003)

| Item | Check |
|---|---|
| `Patient.first_name`, `last_name`, `date_of_birth`, `phone`, `email` use `EncryptedString` (non-deterministic) | ☐ |
| `Patient.mrn_encrypted` uses `DeterministicEncryptedString` with `unique=True` | ☐ |
| `Patient` inherits both `TimestampMixin` and `SoftDeleteMixin` | ☐ |
| If US-007 stub in use: `# TODO(US-007)` comment present in `app/db/encryption.py` | ☐ |
| `AppUser.idp_subject` has `unique=True` | ☐ |
| `AppUser.is_active` defaults `True` with `server_default=sa.true()` | ☐ |
| `Bed` has `UniqueConstraint("unit", "bed_number")` | ☐ |

### ORM Model — Encounter (TASK-004)

| Item | Check |
|---|---|
| `EncounterStatus` enum defines: `REGISTERED`, `ADMITTED`, `TRANSFERRED`, `DISCHARGED` | ☐ |
| `Encounter.status` uses `String(32)` (not a DB-level Enum type — avoids migration complexity) | ☐ |
| `Encounter.patient_id` FK has `ondelete="RESTRICT"` | ☐ |
| `Encounter` inherits both `TimestampMixin` and `SoftDeleteMixin` | ☐ |
| Three composite indexes present per DR-004: `(patient_id, admit_date)`, `(unit, status)`, `(risk_tier, status)` | ☐ |
| `RiskTier` enum defines: `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN` | ☐ |

### ORM Models — Remaining 6 Tables (TASK-005)

| Item | Check |
|---|---|
| `AdtEvent.source_message_id` has `unique=True` and `UniqueConstraint` (DR-022) | ☐ |
| `AgentTask` has `UniqueConstraint("encounter_id", "agent_type", "pubsub_message_id")` for idempotency | ☐ |
| `Document.content` uses `EncryptedString` TypeDecorator (DR-013) | ☐ |
| `AuditLog` does NOT inherit `TimestampMixin` (no `updated_at` — append-only semantics) | ☐ |
| `ChatbotTranscript.message_content` uses `EncryptedString` (DR-016) | ☐ |
| All FK relationships specify explicit `ondelete` behaviour | ☐ |
| `app/models/__init__.py` exports all 10 models | ☐ |

### Encounter State Machine (TASK-006)

| Item | Check |
|---|---|
| `EncounterStateTransitionError` extends `HTTPException` with `status_code=409` | ☐ |
| No PHI (MRN, name, patient ID) in `EncounterStateTransitionError.detail` message | ☐ |
| `@event.listens_for(Encounter.status, "set")` listener registered in `encounter_statemachine.py` | ☐ |
| Non-string `oldvalue` (initial INSERT) bypassed without error | ☐ |
| `_ALLOWED_TRANSITIONS` covers all 5 valid transitions including A13 (marked `None`) | ☐ |
| A13 session flag (`allow_a13_cancel_discharge`) consumed (cleared) after first successful use | ☐ |
| `app/models/__init__.py` imports `encounter_statemachine` to register listener at startup | ☐ |

### Alembic Migrations (TASK-007)

| Item | Check |
|---|---|
| `0001_initial_schema.py` creates all 10 tables in dependency order | ☐ |
| `UniqueConstraint("source_message_id")` present on `adt_event` (DR-022) | ☐ |
| `deleted_at` column present on `patient` and `encounter` (DR-005) | ☐ |
| All 4 DR-004 indexes present: `ix_encounter_patient_admit`, `ix_encounter_unit_status`, `ix_encounter_risk_tier_status`, `ix_patient_mrn_encrypted` | ☐ |
| `0002_audit_log_rls.py` enables RLS on `audit_log` with INSERT/SELECT-only policies | ☐ |
| `0002` creates `fn_audit_log_no_update` trigger as defence-in-depth (DR-003) | ☐ |
| `downgrade()` implemented for both migrations and tested reversible | ☐ |
| No hardcoded DB credentials in any `.py` migration file | ☐ |
| Both migrations have `down_revision` chain forming a linear history | ☐ |

### Integration Tests (TASK-008)

| Item | Check |
|---|---|
| All 16 tests pass (`pytest tests/test_us006_schema.py -v`) | ☐ |
| Tests run against PostgreSQL 15 container (not SQLite) | ☐ |
| Scenario 2 test confirms `EncounterStateTransitionError` is raised BEFORE DB flush (status unchanged) | ☐ |
| Scenario 3 test confirms `IntegrityError` on duplicate MRN | ☐ |
| Scenario 4 test confirms soft-deleted record absent from `WHERE deleted_at IS NULL` query | ☐ |
| Downgrade tests confirm `alembic downgrade -1` (audit_log_rls) and `downgrade base` (initial_schema) complete without error | ☐ |
| No real PHI in test fixtures (synthetic MRN values only) | ☐ |

### Security Review

| Item | Check |
|---|---|
| `grep -rn "password\|secret\|api_key" backend/app/` returns no hardcoded credential values | ☐ |
| `alembic.ini` does not contain `sqlalchemy.url` or any credential pattern | ☐ |
| `EncounterStateTransitionError` does not expose patient IDs in HTTP 409 response body | ☐ |
| Audit log table cannot be updated or deleted by `smarthandoff_app` DB user (RLS + trigger) | ☐ |
| PHI fields on `patient`, `document`, `chatbot_transcript` use TypeDecorators (not plaintext columns) | ☐ |
| No `.tfstate` or `.tfvars` files with real credentials committed | ☐ |

---

## Pull Request Requirements

The PR raising this work must include:

1. **Description** linking all 9 task IDs (TASK-001 through TASK-009)
2. **Test output** from `pytest tests/test_us006_schema.py -v` showing 16 passed (attached as comment)
3. **`alembic history`** output showing the two-migration linear chain
4. **Reviewer**: Senior Backend Engineer; Security Engineer sign-off recommended for audit_log RLS migration
5. **Labels**: `data-layer`, `sprint-1`, `US-006`

---

## Definition of Done

- [ ] All items in the review checklist above are checked
- [ ] PR approved by at least one senior Backend Engineer
- [ ] All CI checks passing (`ruff`, `bandit`, `pytest`, `alembic upgrade head`)
- [ ] PR merged to `main` branch
- [ ] US-006 status updated to `Done` in sprint board

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 through TASK-008 | All preceding tasks | All must be complete before code review begins |

---

## Files Modified

| File | Action |
|---|---|
| _(none — review task only)_ | This task produces no code changes; it gates the PR merge |
