# TASK-005: FastAPI Reconciliation Endpoint and Persistence Query Layer

> **Story:** US-030 | **Effort:** 6 hours | **Layer:** Backend — API  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement `GET /api/v1/encounters/{id}/medications/reconciliation` FastAPI endpoint that returns the stored reconciliation results for an encounter, and the repository function that queries the `medication` table.

---

## Context

Once `MedicationReconciliationAgent` (TASK-004) persists results, clinicians and downstream services need to retrieve them via API. This task creates the read-path: repository query, response schema mapping, and the FastAPI router with proper RBAC, audit logging, and OpenAPI documentation.

**Upstream Dependencies:**
- TASK-001: `Medication` ORM model + `MedicationReconciliationResponse` schema
- TASK-004: Agent persists records this endpoint reads

---

## Scope

### In Scope

1. **`MedicationRepository`** — `backend/app/repositories/medication_repository.py`:
   - `get_reconciliation_results(encounter_id: UUID, session: AsyncSession) -> list[Medication]`
   - Returns all `Medication` records for encounter ordered by `reconciliation_category`, then `name`

2. **FastAPI router** — `backend/app/api/v1/medications.py`:
   - `GET /api/v1/encounters/{encounter_id}/medications/reconciliation`
   - Response model: `MedicationReconciliationResponse` (from TASK-001)
   - Requires JWT + role: `pharmacist`, `physician`, `nurse`, `admin`
   - Returns 404 if encounter not found; 202 if reconciliation not yet complete

3. **Router registration** — register in `backend/app/api/v1/__init__.py`

4. **OpenAPI metadata** — `summary`, `description`, `tags=["medications"]`, response examples

### Out of Scope

- Agent trigger logic (TASK-004)
- Unit tests (TASK-006)
- Medication write/update endpoints (out of story scope)

---

## Acceptance Criteria

### AC1: Endpoint Returns Reconciliation Results
**Given** reconciliation has completed for encounter `enc-abc123`  
**When** `GET /api/v1/encounters/enc-abc123/medications/reconciliation` is called by an authenticated pharmacist  
**Then** response HTTP 200 contains:
- `encounter_id`
- `total_medications` count
- `reconciliation_completed_at` timestamp
- `medications[]` array with each drug's `reconciliation_category`, `pre_admit`, `inpatient`, `discharge` booleans, and `flags`

### AC2: 404 for Unknown Encounter
**Given** encounter `enc-unknown` does not exist in the database  
**When** the endpoint is called  
**Then** HTTP 404 is returned with `{"detail": "Encounter not found"}`

### AC3: 202 if Reconciliation Pending
**Given** encounter exists but `medication` table has no records with `reconciliation_completed_at` set  
**When** the endpoint is called  
**Then** HTTP 202 is returned with `{"detail": "Reconciliation in progress"}`

### AC4: RBAC Enforced
**Given** a request from a user with role `patient`  
**When** the endpoint is called  
**Then** HTTP 403 is returned

### AC5: HIPAA Audit Log Written
**Given** an authorised pharmacist calls the endpoint  
**When** the request is processed  
**Then** an audit log entry is written with `action=READ_MEDICATION_RECONCILIATION`, `encounter_id`, and `user_id`

---

## Implementation Details

### File: `backend/app/repositories/medication_repository.py`

```python
"""Read queries for the medication reconciliation results."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.medication import Medication, ReconciliationCategory


async def get_reconciliation_results(
    encounter_id: UUID,
    session: AsyncSession,
) -> list[Medication]:
    """
    Return all Medication records for an encounter, ordered by category then name.
    Returns empty list if no records found (caller interprets empty vs not-started).
    """
    stmt = (
        select(Medication)
        .where(Medication.encounter_id == encounter_id)
        .order_by(
            Medication.reconciliation_category.nullslast(),
            Medication.name,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_reconciliation_completed_at(
    encounter_id: UUID,
    session: AsyncSession,
) -> str | None:
    """Return reconciliation_completed_at for the encounter if available."""
    stmt = (
        select(Medication.reconciliation_completed_at)
        .where(
            Medication.encounter_id == encounter_id,
            Medication.reconciliation_completed_at.isnot(None),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    ts = result.scalar_one_or_none()
    return ts.isoformat() if ts else None
```

### File: `backend/app/api/v1/medications.py`

```python
"""Medication reconciliation API router."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_roles
from app.core.audit import write_audit_log
from app.db.session import get_db_session
from app.repositories.encounter_repository import get_encounter_by_id
from app.repositories.medication_repository import (
    get_reconciliation_results,
    get_reconciliation_completed_at,
)
from app.schemas.medication import (
    MedicationReconciliationResponse,
    MedicationReconciliationResult,
)
from app.models.medication import MedicationListSource

router = APIRouter(prefix="/encounters", tags=["medications"])

ALLOWED_ROLES = ["pharmacist", "physician", "nurse", "admin"]


@router.get(
    "/{encounter_id}/medications/reconciliation",
    response_model=MedicationReconciliationResponse,
    summary="Get medication reconciliation results for an encounter",
    description=(
        "Returns a three-way medication comparison (pre-admission, inpatient, discharge) "
        "with each drug categorised as CONTINUED, NEW, STOPPED, or DOSE_CHANGED. "
        "Flags include DUPLICATE and STOPPED_WITHOUT_ORDER. "
        "Returns 202 if reconciliation is still in progress."
    ),
    responses={
        200: {"description": "Reconciliation results"},
        202: {"description": "Reconciliation in progress"},
        403: {"description": "Insufficient role"},
        404: {"description": "Encounter not found"},
    },
)
async def get_medication_reconciliation(
    encounter_id: UUID,
    current_user=Depends(require_roles(ALLOWED_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> MedicationReconciliationResponse:
    # 1. Verify encounter exists
    encounter = await get_encounter_by_id(encounter_id, session)
    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    # 2. Fetch reconciliation results
    medications = await get_reconciliation_results(encounter_id, session)

    # 3. 202 if agent has not completed yet
    completed_at = await get_reconciliation_completed_at(encounter_id, session)
    if not medications and not completed_at:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Reconciliation in progress",
        )

    # 4. Write HIPAA audit log
    await write_audit_log(
        action="READ_MEDICATION_RECONCILIATION",
        user_id=current_user.id,
        encounter_id=str(encounter_id),
        session=session,
    )

    # 5. Map ORM records to response schema
    results = [_to_result(m) for m in medications]

    return MedicationReconciliationResponse(
        encounter_id=encounter_id,
        total_medications=len(results),
        reconciliation_completed_at=completed_at,
        medications=results,
    )


def _to_result(med) -> MedicationReconciliationResult:
    """Map Medication ORM record to API response schema."""
    return MedicationReconciliationResult(
        id=med.id,
        name=med.name,
        rxnorm_cui=med.rxnorm_cui,
        reconciliation_category=med.reconciliation_category,
        pre_admit=MedicationListSource.PRE_ADMIT in (med.sources or []),
        inpatient=MedicationListSource.INPATIENT in (med.sources or []),
        discharge=MedicationListSource.DISCHARGE in (med.sources or []),
        flags=med.flags or [],
        dose=f"{med.dose_value} {med.dose_unit}".strip() if med.dose_value else None,
        route=med.route,
        frequency=med.frequency,
    )
```

### Registration in `backend/app/api/v1/__init__.py`

```python
from app.api.v1.medications import router as medications_router
app.include_router(medications_router, prefix="/api/v1")
```

---

## Validation Steps

### Step 1: Endpoint Smoke Test (with test DB)
```bash
# Start test server
uvicorn app.main:app --reload --port 8001

# Call endpoint with test JWT
curl -s -H "Authorization: Bearer $TEST_JWT" \
  http://localhost:8001/api/v1/encounters/$TEST_ENCOUNTER_ID/medications/reconciliation \
  | python -m json.tool

# Expected: 200 with medications array or 202 if pending
```

### Step 2: 404 Validation
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TEST_JWT" \
  http://localhost:8001/api/v1/encounters/00000000-0000-0000-0000-000000000000/medications/reconciliation
# Expected: 404
```

### Step 3: RBAC Validation
```bash
# Use a patient-role JWT
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $PATIENT_JWT" \
  http://localhost:8001/api/v1/encounters/$TEST_ENCOUNTER_ID/medications/reconciliation
# Expected: 403
```

### Step 4: OpenAPI Schema Check
```bash
curl -s http://localhost:8001/openapi.json | python -c "
import json, sys
spec = json.load(sys.stdin)
path = spec['paths'].get('/api/v1/encounters/{encounter_id}/medications/reconciliation', {})
assert path, 'Endpoint not in OpenAPI spec'
print('✓ Endpoint registered in OpenAPI spec')
print('  GET responses:', list(path.get('get', {}).get('responses', {}).keys()))
"
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `encounter_id` type mismatch (str vs UUID) in query | Medium | Medium | Use `UUID` FastAPI path parameter type; SQLAlchemy auto-casts |
| `202` status code rejected by some API clients | Low | Low | Document in OpenAPI; add `Retry-After: 30` header on 202 |
| Large response (>200 meds) exceeds JSON payload limits | Low | Low | Add pagination with `?limit=50&offset=0` params in future sprint |
| `write_audit_log` raises exception — masks actual response | Low | High | Wrap audit log write in `try/except`; log failure but don't fail request |

---

## Definition of Done

- [ ] `get_reconciliation_results` repository function implemented
- [ ] `GET /api/v1/encounters/{id}/medications/reconciliation` endpoint implemented
- [ ] 404 on unknown encounter validated
- [ ] 202 on pending reconciliation validated
- [ ] RBAC enforced for pharmacist/physician/nurse/admin roles
- [ ] HIPAA audit log written on every successful request
- [ ] OpenAPI docs include summary, description, and response examples
- [ ] Router registered in main app
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-001:** Response schemas consumed here
- **TASK-004:** Agent writes records this endpoint reads
- **TASK-006:** Unit tests validate endpoint behaviour

---

## Notes for Implementer

1. **202 vs 404** — Return 202 (Accepted) when the encounter exists but reconciliation hasn't run yet (empty `medication` table for that encounter). Return 404 only when the encounter itself doesn't exist.
2. **`nullslast()` ordering** — SQLAlchemy requires explicit `nullslast()` on nullable enum columns; without it PostgreSQL may order NULLs first.
3. **`_to_result` helper** — Keep the mapping function private and co-located with the router; do not put it in the schema layer to avoid circular imports.
4. **Audit log** — Refer to existing `write_audit_log` signature from other routers in `app/api/v1/`; do not create a new audit helper.

---

*Task created on 2026-07-16 for US-030 by plan-development-tasks workflow.*
