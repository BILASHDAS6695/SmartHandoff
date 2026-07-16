---
id: US-030
title: "Compare Three FHIR Medication Lists and Categorise Changes"
epic: EP-005
sprint: 2
story_points: 5
generated: 2026-07-16
workflow: plan-development-tasks
---

# US-030 Task Index — Three-way FHIR Medication Reconciliation

> **Epic:** EP-005 — Medication Reconciliation Agent | **Sprint:** 2 | **Points:** 5  
> **Total Effort:** 40 hours | **Generated:** 2026-07-16

---

## Task Breakdown Summary

| Task ID | Title | Effort | Layer | File |
|---------|-------|--------|-------|------|
| TASK-001 | Medication ORM Models, Enums, and Alembic Migration | 6h | Data Layer | `task_001_medication_orm_models_enums_migration.md` |
| TASK-002 | FHIR Medication Fetcher — MedicationStatement / MedicationAdministration / MedicationRequest | 8h | FHIR Integration | `task_002_fhir_medication_fetcher.md` |
| TASK-003 | RxNorm Normalisation Service via RxNav API | 6h | External Integration | `task_003_rxnorm_normalisation_service.md` |
| TASK-004 | MedicationReconciliationAgent — Three-way Comparison, Duplicate & Missing Detection | 10h | AI Agent | `task_004_medication_reconciliation_agent.md` |
| TASK-005 | FastAPI Reconciliation Endpoint and Persistence Query Layer | 6h | API | `task_005_fastapi_reconciliation_endpoint.md` |
| TASK-006 | Unit Tests — 15+ Medication Fixtures Covering All Categories | 4h | Testing | `task_006_unit_tests_medication_fixtures.md` |

**Total:** 40 hours = 5 story points ✓

---

## Acceptance Criteria Coverage Matrix

| Acceptance Criteria | Covered By |
|---------------------|------------|
| SC1: Three lists fetched and compared — CONTINUED/NEW/STOPPED/DOSE_CHANGED | TASK-002, TASK-004, TASK-006 |
| SC2: Duplicate medication flagged as DUPLICATE + MEDIUM alert | TASK-004, TASK-006 |
| SC3: Missing chronic flagged as STOPPED_WITHOUT_ORDER + HIGH alert | TASK-004, TASK-006 |
| SC4: Reconciliation persisted and returned via `GET /api/v1/encounters/{id}/medications/reconciliation` | TASK-001, TASK-004, TASK-005 |

---

## Definition of Done Checklist

- [ ] `MedicationReconciliationAgent` extends `BaseAgent` (TASK-004)
- [ ] FHIR fetch: `MedicationStatement`, `MedicationAdministration`, `MedicationRequest` (TASK-002)
- [ ] Normalisation: RxNorm CUI via RxNav (TASK-003)
- [ ] Comparison: CONTINUED / NEW / STOPPED / DOSE_CHANGED (TASK-004)
- [ ] Duplicate detection: same CUI + route → DUPLICATE (TASK-004)
- [ ] Missing chronic: STOPPED without stop order → STOPPED_WITHOUT_ORDER (TASK-004)
- [ ] Results persisted to `medication` ORM table (TASK-004, TASK-001)
- [ ] `GET /api/v1/encounters/{id}/medications/reconciliation` endpoint (TASK-005)
- [ ] Unit tests with 15+ fixtures (TASK-006)
- [ ] Code reviewed and approved (all tasks)

---

## Implementation Order

```
TASK-001 (ORM + Enums)
    │
    ├── TASK-002 (FHIR Fetcher)        ─── parallel ───┐
    └── TASK-003 (RxNorm Normaliser)   ─── parallel ───┘
                                                        │
                                               TASK-004 (Agent)
                                                        │
                                               TASK-005 (API Endpoint)
                                                        │
                                               TASK-006 (Unit Tests)
```

TASK-002 and TASK-003 can be developed in parallel after TASK-001 is complete.

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Separate `RawMedicationEntry` dataclass | Decouples FHIR parsing from comparison logic; enables mocking in tests |
| `asyncio.gather` for FHIR + RxNav batch | Achieves concurrent network I/O without blocking agent loop |
| In-process `dict` cache in `RxNormNormaliser` | Avoids duplicate RxNav calls for same drug on multiple lists; scoped to single agent run |
| `sources: ARRAY[MedicationListSource]` column | Preserves multi-list membership without a join table; enables `pre_admit/inpatient/discharge` boolean derivation at API layer |
| 202 response on pending reconciliation | Signals to API consumers that the agent has not yet completed without returning empty data |

---

## Dependencies

| Dependency | Story | Notes |
|------------|-------|-------|
| `BaseAgent` framework | US-024 | `MedicationReconciliationAgent` extends this |
| FHIR medication resource fetching | US-017 | `FHIRClient` injected into `FHIRMedicationFetcher` |
| `medication` ORM baseline | US-006 | TASK-001 extends existing model |

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| RxNav returns inconsistent CUIs for branded vs generic names | High | Medium | Log CUI misses; fallback to lowercased name comparison |
| `MedicationAdministration` resource not populated by all EHRs | Medium | Low | Return empty inpatient list; reconciliation still works on pre-admit ↔ discharge |
| `BaseAgent.publish_event` not yet available (US-024 dependency) | Medium | Medium | Stub with logger warning until US-024 is merged |
| Alembic migration conflicts with concurrent schema changes | Low | High | Co-ordinate migration sequence in sprint planning; use feature branch per migration |

---

## Validation Approach

Each task includes localised validation steps (bash/Python snippets). Full E2E validation is covered by the separate test plan (`test_plan_EP-005.md`). Post-implementation, run:

```bash
# Run unit tests for this story
cd backend
pytest tests/unit/agents/medication_reconciliation/ tests/unit/api/test_reconciliation_endpoint.py -v

# Coverage report
pytest tests/unit/agents/medication_reconciliation/ \
  --cov=app/agents/medication_reconciliation --cov-report=term-missing

# API smoke test (requires running server + test DB)
curl -s -H "Authorization: Bearer $PHARMACIST_JWT" \
  http://localhost:8000/api/v1/encounters/$TEST_ENCOUNTER_ID/medications/reconciliation \
  | python -m json.tool
```

---

*Task index generated on 2026-07-16 for US-030 by plan-development-tasks workflow.*
