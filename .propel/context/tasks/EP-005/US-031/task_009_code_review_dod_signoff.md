---
id: TASK-009
title: "Code Review and Definition of Done Sign-off — US-031"
user_story: US-031
epic: EP-005
sprint: 2
layer: Quality Assurance
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-001, US-031/TASK-002, US-031/TASK-003, US-031/TASK-004, US-031/TASK-005, US-031/TASK-006, US-031/TASK-007, US-031/TASK-008]
---

# TASK-009: Code Review and Definition of Done Sign-off — US-031

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Quality Assurance | **Est:** 2 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task verifies that all eight implementation tasks for US-031 meet the Definition of Done, passes a structured code review against project standards, and signs off the story before sprint demo. No new code is written — this task is a review and validation gate.

**Design references:**
- US-031 Definition of Done checklist
- design.md — security, RBAC, HIPAA, logging standards
- `.github/instructions/` — security-standards-owasp, backend-development-standards, code-documentation-standards

---

## Review Checklist

### Functional Completeness

- [ ] `DrugInteractionChecker` checks all active discharge drug pairs (not a subset)
- [ ] RxNav batch URL matches spec: `GET https://rxnav.nlm.nih.gov/REST/interaction/list.json?rxcuis={cuis}`
- [ ] Severity mapping: `major`/`contraindicated` → HIGH; `moderate` → MEDIUM; `minor` → LOW
- [ ] Redis key: `drug-interaction:{min_cui}:{max_cui}`, TTL = 86400 s
- [ ] OpenFDA fallback URL: `GET https://api.fda.gov/drug/label.json?search=warnings+interactions:{drug_name}`
- [ ] `interaction_check_status` field present on alert record
- [ ] `POST /api/v1/encounters/{id}/alerts` endpoint responds HTTP 201
- [ ] HIGH interaction → Pub/Sub `priority=IMMEDIATE`
- [ ] All unit tests (TASK-008) passing in CI

### Code Quality

- [ ] All new modules have module-level docstrings with `Design refs` back to US-031 / design.md sections
- [ ] No magic strings — severity levels, source names, and status values use enum/constant
- [ ] No silent exception swallowing — all caught exceptions are logged at `WARNING` or `ERROR`
- [ ] No N+1 queries in alert persistence (single `flush()` per request)
- [ ] HTTP clients use `timeout` parameter on all external calls
- [ ] Description field capped to prevent oversized OpenFDA label payloads

### Security (OWASP / HIPAA)

- [ ] Drug names and CUIs are **not** PHI — confirmed no encryption applied to interaction data
- [ ] No PHI in Redis cache keys or values
- [ ] RBAC enforced on `POST /api/v1/encounters/{id}/alerts` (PHARMACIST | ADMIN only)
- [ ] Internal service-to-service JWT used by `InteractionPipeline._post_alert()`
- [ ] No API keys for RxNav or OpenFDA in source code (both are public APIs — no key needed; confirmed)

### Test Coverage

- [ ] `test_high_severity_interaction_returned_from_rxnav` → PASS
- [ ] `test_cache_hit_suppresses_rxnav_call` → PASS
- [ ] `test_openfda_fallback_on_rxnav_503` → PASS
- [ ] `test_offline_degradation_when_both_apis_unavailable` → PASS
- [ ] `test_severity_mapping` (parametrised, 10 cases) → PASS
- [ ] `test_cache_key_is_order_independent` → PASS
- [ ] Alert endpoint tests → PASS

### Migration

- [ ] `alembic upgrade head` applied to dev environment without errors
- [ ] `alembic downgrade -1` tested and reverts cleanly
- [ ] `pharmacist_alerts` table present with correct columns and indexes

### Performance

- [ ] RxNav batch call uses single HTTP request for all CUIs (not one call per drug)
- [ ] Cache lookup uses `O(n²/2)` pair combinations — acceptable for ≤50 medications

---

## Sign-off Gate

All items above must be checked before this task is marked **Done**. Any blocking finding creates a follow-up bug task; non-blocking findings are logged in `.propel/learnings/findings-registry.md`.

---

## Definition of Done

- [ ] All checklist items verified
- [ ] Pull request approved by ≥1 reviewer
- [ ] US-031 status updated to `Done` in sprint board
- [ ] No open HIGH/CRITICAL findings from code review
