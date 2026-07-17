---
id: TASK-004
title: "Code Review & DoD Sign-off — US-037 Bed Recommendation Scoring"
user_story: US-037
epic: EP-006
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-037/TASK-001, US-037/TASK-002, US-037/TASK-003]
---

# TASK-004: Code Review & DoD Sign-off — US-037 Bed Recommendation Scoring

> **Story:** US-037 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-037. It verifies that all implementation tasks (TASK-001 through TASK-003) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is required** for this story due to two risk surfaces:

### 1. PHI containment in bed recommendation (HIPAA / BR-020, AIR-021)

The `GET /api/v1/beds/recommend` endpoint processes patient attributes from the `ADTEvent` record (acuity, admit type, isolation status, gender) to build the `PatientAdmissionProfile`. These are coded/categorical values, not raw PHI, but the following must be confirmed:

- **`PatientAdmissionProfile`** contains no `first_name`, `last_name`, `dob`, `mrn`, or `phone` fields — uses coded values only (`acuity_level`, `admit_type`, `isolation_required`, `gender`).
- **Scoring module logs** (`algorithm.py`, `factors.py`) include only `bed_id`, `encounter_id`, and scoring metadata — no patient name, DOB, or MRN.
- **Audit log metadata** in the endpoint includes only `encounter_id` (UUID), `candidate_bed_count`, `recommendation_count`, and `target_unit` — no PHI fields.
- **`score_breakdown`** in the API response contains only normalised float scores — no patient data leaked into the response body beyond what is already exposed at the encounter layer.

### 2. RBAC enforcement on bed recommendation endpoint (SEC-001 / design.md §8.3)

- **`GET /api/v1/beds/recommend`** is restricted to `BedManager` and `Admin` roles (`require_role(["BedManager", "Admin"])`).
- Unauthenticated requests return HTTP 401 — confirmed by `test_recommend_rejects_unauthenticated_request`.
- Nurse or Pharmacist role → HTTP 403 — confirm no permission bypass via query parameter injection.
- `encounter_id` path parameter is validated as UUID; non-UUID input returns 422 (FastAPI automatic validation) — prevents enumeration attacks via malformed IDs.

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# 1. Python linting and security scan
cd backend && ruff check app/agents/bed_management/scoring/ && \
  bandit -r app/agents/bed_management/scoring/ -ll

cd api-gateway && ruff check app/routers/beds.py && \
  bandit -r app/routers/beds.py -ll

# 2. Unit tests with coverage
pytest backend/tests/unit/agents/bed_management/scoring/ \
       api-gateway/tests/unit/routers/test_beds_recommend_endpoint.py \
       -v --cov=app --cov-report=term-missing

# 3. Container build — no CRITICAL CVEs
docker build -t smarthandoff/api-gateway:us037 api-gateway/
docker build -t smarthandoff/bed-mgmt-agent:us037 backend/

# 4. Manual smoke test against staging
curl -s -H "Authorization: Bearer $STAGING_JWT" \
  "https://api.staging.smarthandoff.internal/api/v1/beds/recommend?encounter_id=$TEST_ENCOUNTER_ID" \
  | jq '.recommendations | length'
# Expected: ≥3
```

---

## Definition of Done Checklist

Map to US-037 DoD items:

| DoD Item | Task | Verified |
|----------|------|---------|
| `BedScoringAlgorithm` class with configurable weight YAML | TASK-001 | [ ] |
| Scoring factors: `acuity_match`, `care_type_match`, `isolation_match`, `gender_match` (each 0–1) | TASK-001 | [ ] |
| `GET /api/v1/beds/recommend` endpoint returns top 5 | TASK-002 | [ ] |
| Recommendation result includes `score_breakdown` | TASK-002 | [ ] |
| No-beds scenario: advisory with nearest unit and estimated wait | TASK-002 | [ ] |
| Unit tests: scoring weights, isolation filter, no-beds advisory | TASK-003 | [ ] |
| Code reviewed and approved | TASK-004 | [ ] |

---

## Review Checklist

### Functional
- [ ] `score_and_rank()` returns ≤5 results sorted descending
- [ ] Isolation-required patient: non-isolation beds absent from recommendations
- [ ] Score formula matches weight YAML: `acuity×0.4 + care_type×0.35 + isolation×0.15 + gender×0.10`
- [ ] Weights validate (sum = 1.0 ± 0.001) on load
- [ ] Advisory includes `available_unit` and `estimated_wait_minutes` when alternate unit exists
- [ ] Advisory message correctly names the exhausted unit

### Security
- [ ] No PHI fields in `PatientAdmissionProfile` (coded values only)
- [ ] No PHI in scoring module log statements
- [ ] Audit metadata contains only UUIDs, counts, and unit names — no patient identifiers
- [ ] Endpoint enforces `BedManager` / `Admin` RBAC
- [ ] `encounter_id` UUID validation blocks non-UUID input (HTTP 422)
- [ ] `ruff` + `bandit -ll` report zero issues on all new files

### Quality
- [ ] Branch coverage ≥80% on all new modules
- [ ] No magic numbers — acuity hierarchy list and score constants are named/documented
- [ ] `bed_scoring_weights.yaml` committed to version control with comment explaining reload behaviour
- [ ] Container images scan clean (no CRITICAL CVEs) via Artifact Registry

---

## Reviewer Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Backend Engineer | | | |
| Security Engineer | | | |
| Tech Lead | | | |
