---
id: TASK-009
title: "Code Review and Definition of Done Sign-off — US-032"
user_story: US-032
epic: EP-005
sprint: 2
layer: Quality Assurance
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-032/TASK-001, US-032/TASK-002, US-032/TASK-003, US-032/TASK-004, US-032/TASK-005, US-032/TASK-006, US-032/TASK-007, US-032/TASK-008]
---

# TASK-009: Code Review and Definition of Done Sign-off — US-032

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Quality Assurance | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task verifies that all eight implementation tasks for US-032 meet the Definition of Done, passes a structured code review against project standards, and signs off the story before sprint demo. No new code is written — this task is a review and validation gate.

**Design references:**
- US-032 Definition of Done checklist
- design.md — security, RBAC, HIPAA, logging standards
- `.github/instructions/` — security-standards-owasp, backend-development-standards, code-documentation-standards

---

## Review Checklist

### Functional Completeness

- [ ] `config/high_risk_drugs.yaml` present with all four mandatory ISMP classes: `ANTICOAGULANT`, `INSULIN`, `OPIOID`, `CHEMOTHERAPY`
- [ ] `HighRiskDrugClassDetector.detect()` performs case-insensitive, dose-stripped matching against YAML config
- [ ] Detection is **unconditional** — runs regardless of interaction check result
- [ ] Detection is **additive** — a drug can produce both a `PHARMACIST_ALERT` and a `HIGH_RISK_DRUG_CLASS` alert
- [ ] `alert_type=HIGH_RISK_DRUG_CLASS`, `drug_class`, `drug_name`, `severity=HIGH` persisted on alert record
- [ ] `PATCH /api/v1/alerts/{id}/resolve` endpoint responds HTTP 200 with updated `AlertRead` on valid pharmacist call
- [ ] `status=RESOLVED`, `resolved_by_user_id`, `resolved_at` set correctly on resolution
- [ ] Resolved alert no longer appears in the active pharmacist alert queue
- [ ] `AlertSLAMonitor.run()` detects alerts ≥ 24h unresolved and tags `sla_breached=True`
- [ ] `CHARGE_PHARMACIST_ESCALATION` Pub/Sub message published with `priority=IMMEDIATE`
- [ ] SLA monitor is idempotent — re-run does not re-publish already-escalated alerts
- [ ] Cloud Scheduler cron `*/30 * * * *` configured for SLA monitor job
- [ ] All unit tests from TASK-008 passing in CI

### Code Quality

- [ ] All new modules have module-level docstrings with `Design refs` back to US-032 / design.md sections
- [ ] No magic strings — drug class names, severity values, resolution types, alert types use constants or enum patterns
- [ ] No silent exception swallowing — all caught exceptions logged at `WARNING` or `ERROR`
- [ ] YAML config loaded once at module import (singleton) — not per-request
- [ ] `InteractionPipeline.run()` uses `asyncio.gather` for parallel execution of interaction check and high-risk detection
- [ ] No N+1 queries in alert persistence — single `flush()` per pipeline invocation per alert
- [ ] HTTP clients use `timeout` on all external calls

### Security (OWASP / HIPAA)

- [ ] Drug names and drug classes are **not** PHI — confirmed no field-level encryption applied
- [ ] `PATCH /api/v1/alerts/{id}/resolve` enforces `PHARMACIST` role via `require_role` dependency — tested with nurse JWT returning 403
- [ ] `resolved_by_user_id` populated from JWT sub claim, not from request body (prevents impersonation)
- [ ] Internal service-to-service calls from pipeline to `POST /api/v1/encounters/{id}/alerts` carry a signed service JWT
- [ ] `sla_breached` field is server-side only — not writable via any public API endpoint

### Migration

- [ ] `alembic upgrade head` applied to dev environment without errors
- [ ] `alembic downgrade -1` tested and reverts cleanly
- [ ] `pharmacist_alerts` table contains all new columns: `drug_class`, `drug_name`, `status`, `resolution_type`, `resolution_note`, `resolved_by_user_id`, `resolved_at`, `sla_breached`
- [ ] Existing pre-migration rows have `status = 'ACTIVE'` after backfill
- [ ] New enum types `alert_status_enum` and `alert_resolution_type_enum` present in PostgreSQL

### Test Coverage

- [ ] `test_detects_high_risk_drug_class` (13 parametrised cases — all four ISMP classes) → PASS
- [ ] `test_non_high_risk_drug_returns_no_match` → PASS
- [ ] `test_detection_is_case_insensitive` → PASS
- [ ] `test_multiple_high_risk_drugs_returns_multiple_matches` → PASS
- [ ] `test_dose_stripped_before_matching` → PASS
- [ ] `test_pharmacist_can_resolve_active_alert` → PASS
- [ ] `test_nurse_cannot_resolve_alert` (HTTP 403) → PASS
- [ ] `test_resolve_unknown_alert_returns_404` → PASS
- [ ] `test_resolve_already_resolved_alert_returns_409` → PASS
- [ ] `test_sla_breached_alert_is_tagged_and_escalated` → PASS
- [ ] `test_sla_monitor_is_idempotent` → PASS
- [ ] `test_sla_monitor_continues_on_single_alert_failure` → PASS

### Definition of Done Verification

| DoD Item | Status |
|----------|--------|
| `HighRiskDrugClassDetector` class with configurable YAML | ☐ |
| High-risk classes: ANTICOAGULANT, INSULIN, OPIOID, CHEMOTHERAPY | ☐ |
| Drug-to-class mapping: `config/high_risk_drugs.yaml` | ☐ |
| `POST /api/v1/encounters/{id}/alerts` stores HIGH_RISK_DRUG_CLASS alerts | ☐ |
| `PATCH /api/v1/alerts/{id}/resolve` with RBAC (pharmacist-only) | ☐ |
| Alert SLA monitor: 24h threshold | ☐ |
| Unit tests: each high-risk class, RBAC enforcement, SLA breach | ☐ |
| Code reviewed and approved | ☐ |

---

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Implementing Engineer | | 2026-07-__ | |
| Reviewer | | 2026-07-__ | |
| Sprint Lead | | 2026-07-__ | |
