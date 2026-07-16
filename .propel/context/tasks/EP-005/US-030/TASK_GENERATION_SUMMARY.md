# US-030 Task Generation Summary

**Story:** US-030 — Compare Three FHIR Medication Lists and Categorise Changes  
**Generated:** 2026-07-16  
**Workflow:** plan-development-tasks

---

## Generated Artifacts

### Index File

- **File:** `US-030-tasks-index.md`
- **Content:** Task breakdown summary, acceptance criteria coverage matrix, DoD checklist, implementation order, technical decisions, dependencies, risks, validation approach

### Task Files

| Task ID | Title | Effort | File |
|---------|-------|--------|------|
| TASK-001 | Medication ORM Models, Enums, and Alembic Migration | 6h | `task_001_medication_orm_models_enums_migration.md` |
| TASK-002 | FHIR Medication Fetcher — MedicationStatement / MedicationAdministration / MedicationRequest | 8h | `task_002_fhir_medication_fetcher.md` |
| TASK-003 | RxNorm Normalisation Service via RxNav API | 6h | `task_003_rxnorm_normalisation_service.md` |
| TASK-004 | MedicationReconciliationAgent — Three-way Comparison, Duplicate & Missing Detection | 10h | `task_004_medication_reconciliation_agent.md` |
| TASK-005 | FastAPI Reconciliation Endpoint and Persistence Query Layer | 6h | `task_005_fastapi_reconciliation_endpoint.md` |
| TASK-006 | Unit Tests — 15+ Medication Fixtures Covering All Categories | 4h | `task_006_unit_tests_medication_fixtures.md` |

**Total Effort:** 40 hours = 5 story points ✓

---

## Task Breakdown Rationale

### TASK-001: Foundation (6h)
- **Scope:** ORM model extension with reconciliation fields, three enums, Pydantic response schemas, Alembic migration
- **Why First:** All downstream tasks depend on `ReconciliationCategory`, `ReconciliationFlag`, `MedicationListSource` enums and the `Medication` ORM schema
- **Key Deliverables:**
  - `ReconciliationCategory`, `ReconciliationFlag`, `MedicationListSource` enums
  - `Medication` ORM model with `rxnorm_cui`, `reconciliation_category`, `flags`, `sources`, `dose_value`, `dose_unit`, `route`, `frequency`
  - `MedicationReconciliationResult` and `MedicationReconciliationResponse` Pydantic schemas
  - Alembic migration script (up + down tested)

### TASK-002: FHIR Integration (8h)
- **Scope:** Async FHIR fetcher for three FHIR resource types, shared `RawMedicationEntry` intermediate model
- **Why Second (parallel with TASK-003):** Provides the raw medication data that the agent processes; each resource type (`MedicationStatement`, `MedicationAdministration`, `MedicationRequest`) has distinct field structures requiring dedicated parsers
- **Key Deliverables:**
  - `RawMedicationEntry` dataclass
  - `FHIRMedicationFetcher` with concurrent `fetch_all` using `asyncio.gather`
  - Three private FHIR resource parsers
  - Shared dose/route/frequency extractors

### TASK-003: Normalisation (6h)
- **Scope:** RxNorm CUI lookup via RxNav REST API with in-process cache, dose string parser
- **Why Parallel with TASK-002:** Independent of FHIR fetching; outputs directly consumed by TASK-004
- **Key Deliverables:**
  - `RxNormNormaliser` with `normalise`, `normalise_batch`, in-process `dict` cache
  - Non-fatal timeout/error handling returning `None`
  - `DoseParser.parse_dose` regex-based utility
  - `RXNAV_BASE_URL` and `RXNAV_TIMEOUT_SECONDS` settings

### TASK-004: Core Agent (10h)
- **Scope:** `MedicationReconciliationAgent` orchestrating full pipeline, comparison algorithm, duplicate detection, missing chronic detection, pharmacist alerts, DB persistence
- **Why Fourth:** Depends on all previous tasks; highest complexity task in the story
- **Key Deliverables:**
  - `MedicationReconciliationAgent` extending `BaseAgent`
  - `_compare` producing CONTINUED / NEW / STOPPED / DOSE_CHANGED categories
  - `_detect_duplicates` flagging same-CUI + same-route discharge pairs
  - `_detect_missing_chronic` with FHIR stop-order verification
  - `_create_alerts` publishing to `pharmacist-alerts` Pub/Sub topic
  - Full persistence of `Medication` ORM records

### TASK-005: API Endpoint (6h)
- **Scope:** Read-path: repository query, `GET /api/v1/encounters/{id}/medications/reconciliation`, RBAC, audit log, 202/404 handling
- **Why Fifth:** Reads records written by TASK-004; defines the public contract for the reconciliation feature
- **Key Deliverables:**
  - `get_reconciliation_results` repository function
  - FastAPI router with 200 / 202 / 403 / 404 response handling
  - HIPAA audit log on every authorised request
  - OpenAPI documentation with response examples

### TASK-006: Unit Tests (4h)
- **Scope:** 15+ parameterised fixtures, category tests, duplicate/missing tests, dose parser tests, RxNorm cache tests, API endpoint tests
- **Why Last:** Validates all previously implemented components; written after implementation to maximise fixture realism
- **Key Deliverables:**
  - 15 parameterised medication fixtures (fixture-01 through fixture-15)
  - Duplicate detection edge cases (same route vs different route)
  - Missing chronic with/without stop order
  - Dose parser: 5 valid + 4 invalid cases
  - RxNorm cache, unknown-drug, timeout tests
  - API: 200, 202, 403, 404 scenario tests

---

## Acceptance Criteria Coverage

| Scenario | Tasks |
|----------|-------|
| SC1: Three-list comparison → CONTINUED/NEW/STOPPED/DOSE_CHANGED | TASK-002, TASK-004, TASK-006 |
| SC2: Duplicate detection → DUPLICATE flag + MEDIUM alert | TASK-004, TASK-006 |
| SC3: Missing chronic → STOPPED_WITHOUT_ORDER flag + HIGH alert | TASK-004, TASK-006 |
| SC4: Results returned via GET endpoint | TASK-001, TASK-004, TASK-005 |

---

## Implementation Order

```
TASK-001 ──► TASK-002 ──┐
             TASK-003 ──┴──► TASK-004 ──► TASK-005 ──► TASK-006
```

---

## Files Created

| File | Purpose |
|------|---------|
| `US-030-tasks-index.md` | Master index with coverage matrix and implementation order |
| `task_001_medication_orm_models_enums_migration.md` | ORM models, enums, Alembic migration |
| `task_002_fhir_medication_fetcher.md` | Async FHIR medication list fetcher |
| `task_003_rxnorm_normalisation_service.md` | RxNorm CUI lookup + dose parser |
| `task_004_medication_reconciliation_agent.md` | Core reconciliation agent |
| `task_005_fastapi_reconciliation_endpoint.md` | Read API endpoint |
| `task_006_unit_tests_medication_fixtures.md` | 15+ fixture unit tests |
| `TASK_GENERATION_SUMMARY.md` | This file |

---

## Next Steps for Implementation

1. **Review:** Tech Lead and Clinical Pharmacist SME review task breakdown for clinical accuracy
2. **Assign:** Distribute TASK-001 to backend engineer; TASK-002 + TASK-003 in parallel sprint; TASK-004 to AI/ML engineer
3. **TASK-001:** Implement ORM foundation first — gate for all other tasks
4. **TASK-002 + TASK-003:** Implement concurrently in parallel branches
5. **TASK-004:** Implement agent after TASK-001 through TASK-003 merged
6. **TASK-005:** Implement endpoint after TASK-004 is complete and persisting records
7. **TASK-006:** Write unit tests; run coverage check (≥80%)
8. **Code Review:** Peer review all implementations; clinical pharmacist validates categorisation logic
9. **Deploy:** Merge to `build/development`; smoke test against staging FHIR server

---

*Task generation completed on 2026-07-16 by plan-development-tasks workflow.*
