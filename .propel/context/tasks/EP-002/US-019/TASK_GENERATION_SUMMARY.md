# US-019 Task Generation Summary

**Story:** US-019 — Resolve Patient Identity from FHIR via MRN with Partial-Match Fallback  
**Generated:** 2026-07-16  
**Workflow:** plan-development-tasks

---

## Generated Artifacts

### Index File
- **File:** `US-019-tasks-index.md`
- **Content:** Task breakdown summary, acceptance criteria coverage matrix, DoD checklist, implementation order, technical notes, dependencies, risks, validation steps

### Task Files

| Task ID | Title | Effort | File |
|---------|-------|--------|------|
| TASK-001 | Implement Patient Models, Custom Exceptions, and FHIR Query Builders | 6h | `task_001_patient_models_exceptions_queries.md` |
| TASK-002 | Implement PatientResolver Service with Cascading Resolution Logic | 8h | `task_002_patient_resolver_service.md` |
| TASK-003 | Implement Encounter Status Management and Care Team Alert Dispatch | 6h | `task_003_encounter_status_alert_dispatch.md` |
| TASK-004 | Write Comprehensive Unit Tests for All Resolution Paths | 4h | `task_004_unit_tests_patient_resolution.md` |

**Total Effort:** 24 hours = 3 story points ✓

---

## Task Breakdown Rationale

### TASK-001: Foundation (6h)
- **Scope:** Data models, enums, exceptions, query builders
- **Why First:** All other tasks depend on these foundational structures
- **Key Deliverables:**
  - `PatientModel` with `resolution_method` and `partial_match` fields
  - `ResolutionMethod` and `PatientResolutionStatus` enums
  - `PatientAmbiguousError` and `PatientNotFoundWarning` exceptions
  - FHIR query builders for MRN and name+DOB
  - `FHIR_MRN_SYSTEM_URI` configuration setting

### TASK-002: Core Logic (8h)
- **Scope:** PatientResolver service with cascading resolution
- **Why Second:** Implements main business logic using TASK-001 foundations
- **Key Deliverables:**
  - `resolve_patient()` with MRN → name+DOB fallback
  - Ambiguous match detection (>1 results)
  - Unresolvable case handling (0 results)
  - FHIR response parsing and model mapping
  - Integration with US-017 FHIR client and US-018 resilience

### TASK-003: Integration (6h)
- **Scope:** Encounter status tracking and care team alerts
- **Why Third:** Bridges resolution logic with downstream workflows
- **Key Deliverables:**
  - `CareTeamAlertService` for Pub/Sub dispatch
  - Encounter `patient_resolution_status` field usage
  - Agent task blocking for unresolved encounters
  - Non-blocking alert dispatch

### TASK-004: Validation (4h)
- **Scope:** Comprehensive unit tests
- **Why Last:** Validates all implementations from TASK-001–003
- **Key Deliverables:**
  - 20 unit tests covering all 4 AC scenarios
  - Mocked FHIR and Pub/Sub calls
  - ≥90% code coverage
  - Test execution <30 seconds

---

## Acceptance Criteria Coverage

All 4 US-019 acceptance criteria are fully covered:

| AC Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 |
|-------------|:--------:|:--------:|:--------:|:--------:|
| AC1: Patient resolved by MRN | ✓ | ✓ | | ✓ |
| AC2: Patient resolved by name+DOB fallback | ✓ | ✓ | | ✓ |
| AC3: Ambiguous match → alert | ✓ | ✓ | ✓ | ✓ |
| AC4: Unresolvable → partial encounter | ✓ | ✓ | ✓ | ✓ |

---

## Implementation Order

```
TASK-001 (Foundation)
    ↓
TASK-002 (Core Logic)
    ↓
TASK-003 (Integration)
    ↓
TASK-004 (Tests)
```

Each task builds on the previous, ensuring clean dependency management.

---

## Key Technical Decisions

1. **Configurable MRN System URI:** Different hospitals use different FHIR identifier systems. The `FHIR_MRN_SYSTEM_URI` setting (TASK-001) allows environment-specific configuration.

2. **Stateless Service Pattern:** `PatientResolver` (TASK-002) is stateless with dependency injection, enabling easy testing and horizontal scaling.

3. **Non-Blocking Alert Dispatch:** Care team alerts (TASK-003) are fire-and-forget via Pub/Sub. Alert failures log errors but don't block encounter creation.

4. **Resolution Status at Encounter Level:** The `patient_resolution_status` field lives on `Encounter`, not `Patient`. This correctly models that resolution status is per-encounter, not per-patient record.

5. **Agent Task Blocking:** Tasks for unresolved encounters are created immediately with `status=BLOCKED` rather than delayed. This provides visibility in the dashboard and preserves audit trail.

---

## Validation Approach

Each task includes:
- **Validation Steps:** Manual smoke tests for implementers
- **Testing Strategy:** Unit test plan (deferred to TASK-004)
- **Definition of Done:** Explicit checklist

TASK-004 provides comprehensive test coverage with:
- 12 tests for PatientResolver
- 4 tests for CareTeamAlertService
- 4 tests for encounter status management
- ≥90% code coverage target
- <30 second test execution time

---

## Dependencies & Integration Points

### Upstream Dependencies
- **US-017:** FHIR fetch infrastructure (FHIR client)
- **US-018:** Resilience wrappers (circuit breaker, retry)
- **AIR-014:** FHIR R4 integration architecture
- **FR-003:** Patient identity resolution requirement
- **DR-024:** Patient data model requirements

### Downstream Consumers
- **Encounter creation workflow:** Uses resolution results
- **Agent orchestration:** Blocked by unresolved patients
- **Care team dashboard:** Displays alerts and resolution status
- **Audit system:** Logs all resolution attempts

---

## Risks & Mitigations

| Risk | Mitigation (Task) |
|------|-------------------|
| MRN system URI mismatch across environments | Configurable setting (TASK-001) |
| Name+DOB false positives | WARNING logs + manual review alerts (TASK-002, TASK-003) |
| FHIR server partial responses | Defensive parsing with error logging (TASK-002) |
| Alert dispatch failures block workflow | Non-blocking fire-and-forget (TASK-003) |
| Ambiguous patients overwhelming care team | Alert payload includes full context for triage (TASK-003) |

---

## Files Created

```
.propel/context/tasks/EP-002/US-019/
├── US-019-tasks-index.md                              # Index file
├── task_001_patient_models_exceptions_queries.md      # TASK-001
├── task_002_patient_resolver_service.md               # TASK-002
├── task_003_encounter_status_alert_dispatch.md        # TASK-003
└── task_004_unit_tests_patient_resolution.md          # TASK-004
```

---

## Next Steps for Implementation

1. **Review:** Product Owner and Tech Lead review task breakdown
2. **Assign:** Distribute tasks to backend engineers
3. **TASK-001:** Implement foundation (models, exceptions, queries)
4. **TASK-002:** Implement core resolver logic
5. **TASK-003:** Integrate with encounter workflow
6. **TASK-004:** Write comprehensive tests
7. **Code Review:** Peer review all implementations
8. **QA:** Manual E2E testing with test FHIR server
9. **Deploy:** Merge to development branch

---

*Task generation completed on 2026-07-16 by plan-development-tasks workflow.*
