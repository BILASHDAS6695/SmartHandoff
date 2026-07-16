# TASK-003: Implement Patient Resolution Logic with MRN Fallback to Name+DOB

> **Story:** US-017 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend | **Est:** 8 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements patient resolution logic in `FHIRClient` with MRN-first search and fallback to name+DOB if MRN not found. The `PatientModel` includes `resolution_method` and `partial_match` fields to track how the patient was resolved, enabling downstream agents to apply appropriate validation and escalation logic.

**Design references:**
- US-017 AC Scenario 1 — MRN returns PatientModel with validated fields
- US-017 AC Scenario 2 — MRN fallback to name+DOB with partial_match flag
- AIR-014 — Patient resolution with MRN → name+DOB → unresolvable (warning log)
- US-017 Technical Notes — FHIR search parameters

---

## Acceptance Criteria Addressed

- AC Scenario 1: Patient fetched by MRN returns typed `PatientModel`
- AC Scenario 2: MRN not found falls back to name+DOB search with `partial_match=True`
- AIR-014: Patient resolution logic with three-tier fallback

---

## Implementation Steps

### 1. Add `get_patient_by_mrn()` method to `backend/app/core/fhir/client.py`

Extend `FHIRClient` with patient resolution logic:

```python
# Add to backend/app/core/fhir/client.py

import asyncio  # Add this import at the top if not already present

from app.core.fhir.models import PatientModel, PatientResolutionMethod
from fhir.resources.patient import Patient


class FHIRClient:
    # ... existing methods ...

    @rate_limited
    @circuit_breaker
    async def get_patient_by_mrn(
        self,
        mrn: str,
        fallback_name: str | None = None,
        fallback_dob: str | None = None,
    ) -> PatientModel | None:
        """Fetch Patient resource by MRN with name+DOB fallback.

        Resolution strategy (AIR-014):
        1. Search by MRN in Patient.identifier (primary method)
        2. If not found and fallback params provided: search by name + birthdate
        3. If still not found: log warning and return None

        Args:
            mrn: Medical Record Number (e.g., "MRN-001")
            fallback_name: Patient family name for fallback search (optional)
            fallback_dob: Patient birth date in YYYY-MM-DD format (optional)

        Returns:
            PatientModel with resolution_method and partial_match fields, or None if unresolved

        Raises:
            FHIRValidationError: If resource invalid
            httpx.HTTPError: If request fails after retries
            CircuitBreakerError: If circuit breaker open

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.

        Example:
            # MRN search
            patient = await client.get_patient_by_mrn("MRN-001")

            # MRN with fallback
            patient = await client.get_patient_by_mrn(
                mrn="MRN-UNKNOWN",
                fallback_name="Smith",
                fallback_dob="1980-01-01"
            )
        """
        # Step 1: Try MRN search
        url = f"{self._settings.FHIR_BASE_URL}/Patient"
        # Construct identifier search: system|value
        # System typically: http://hospital.org/mrn (configurable in settings)
        mrn_system = getattr(self._settings, "FHIR_MRN_SYSTEM", "http://hospital.org/mrn")
        params = {"identifier": f"{mrn_system}|{mrn}"}

        try:
            fhir_json = await self._fetch_with_retry(url, params)
            bundle = Bundle(**fhir_json)

            if bundle.entry and len(bundle.entry) > 0:
                # MRN match found
                fhir_patient = Patient(**bundle.entry[0].resource.dict())
                patient_model = PatientModel.from_fhir(fhir_patient)
                patient_model.resolution_method = PatientResolutionMethod.MRN
                patient_model.partial_match = False

                logger.info(
                    "Patient resolved by MRN",
                    extra={
                        "event": "patient_resolution_mrn",
                        "mrn": mrn,
                        "patient_id": patient_model.id,
                    },
                )
                return patient_model

        except Exception as exc:
            logger.warning(
                "MRN search failed — will try fallback if available",
                extra={
                    "event": "patient_resolution_mrn_failed",
                    "mrn": mrn,
                    "error": str(exc),
                },
            )

        # Step 2: MRN not found — try name+DOB fallback
        if fallback_name and fallback_dob:
            logger.info(
                "MRN not found — attempting name+DOB fallback",
                extra={
                    "event": "patient_resolution_fallback",
                    "mrn": mrn,
                    "fallback_name": fallback_name,
                    "fallback_dob": fallback_dob,
                },
            )

            params_fallback = {"family": fallback_name, "birthdate": fallback_dob}

            try:
                fhir_json_fallback = await self._fetch_with_retry(url, params_fallback)
                bundle_fallback = Bundle(**fhir_json_fallback)

                if bundle_fallback.entry and len(bundle_fallback.entry) > 0:
                    if len(bundle_fallback.entry) > 1:
                        # Multiple matches — log warning but use first result
                        logger.warning(
                            "Name+DOB fallback returned multiple matches — using first",
                            extra={
                                "event": "patient_resolution_multiple_matches",
                                "match_count": len(bundle_fallback.entry),
                            },
                        )

                    fhir_patient_fallback = Patient(**bundle_fallback.entry[0].resource.dict())
                    patient_model_fallback = PatientModel.from_fhir(fhir_patient_fallback)
                    patient_model_fallback.resolution_method = PatientResolutionMethod.NAME_DOB
                    patient_model_fallback.partial_match = True

                    logger.warning(
                        "Patient resolved by name+DOB fallback — partial match",
                        extra={
                            "event": "patient_resolution_name_dob",
                            "mrn": mrn,
                            "patient_id": patient_model_fallback.id,
                            "partial_match": True,
                        },
                    )
                    return patient_model_fallback

            except Exception as exc:
                logger.warning(
                    "Name+DOB fallback search failed",
                    extra={
                        "event": "patient_resolution_fallback_failed",
                        "error": str(exc),
                    },
                )

        # Step 3: Both resolution methods failed — return None
        logger.warning(
            "Patient unresolvable — both MRN and name+DOB searches failed",
            extra={
                "event": "patient_resolution_unresolvable",
                "mrn": mrn,
                "fallback_provided": bool(fallback_name and fallback_dob),
            },
        )
        return None
```

---

### 2. Add `FHIR_MRN_SYSTEM` to `backend/app/core/config.py`

Add configurable MRN identifier system:

```python
# Add to backend/app/core/config.py Settings class

class Settings(BaseSettings):
    # ... existing FHIR fields ...

    FHIR_MRN_SYSTEM: str = Field(
        default="http://hospital.org/mrn",
        description=(
            "FHIR identifier system for Medical Record Number (MRN). "
            "Used in Patient?identifier={system}|{mrn} searches. "
            "Default: 'http://hospital.org/mrn'"
        ),
    )
```

---

## Validation

### Test patient resolution scenarios

```bash
cd backend

# Test MRN hit
python -c "
import asyncio
from app.core.fhir import FHIRClient

async def test_mrn_hit():
    client = FHIRClient()
    
    try:
        # Replace with valid test MRN
        patient = await client.get_patient_by_mrn('MRN-001')
        
        if patient:
            assert patient.resolution_method == 'MRN'
            assert patient.partial_match is False
            print(f'✓ MRN hit: {patient.id} ({patient.family_name}, {patient.given_name})')
        else:
            print('✗ Patient not found')
    finally:
        await client.close()

asyncio.run(test_mrn_hit())
"

# Test MRN miss with name+DOB fallback
python -c "
import asyncio
from app.core.fhir import FHIRClient

async def test_fallback():
    client = FHIRClient()
    
    try:
        # Invalid MRN but valid name+DOB
        patient = await client.get_patient_by_mrn(
            mrn='MRN-INVALID',
            fallback_name='Smith',
            fallback_dob='1980-01-01'
        )
        
        if patient:
            assert patient.resolution_method == 'NAME_DOB'
            assert patient.partial_match is True
            print(f'✓ Name+DOB fallback: {patient.id} (partial_match=True)')
        else:
            print('✗ Patient not found even with fallback')
    finally:
        await client.close()

asyncio.run(test_fallback())
"

# Test unresolvable patient
python -c "
import asyncio
from app.core.fhir import FHIRClient

async def test_unresolvable():
    client = FHIRClient()
    
    try:
        # Invalid MRN and invalid name+DOB
        patient = await client.get_patient_by_mrn(
            mrn='MRN-NONEXISTENT',
            fallback_name='ZZZ',
            fallback_dob='1900-01-01'
        )
        
        assert patient is None
        print('✓ Unresolvable patient returns None')
    finally:
        await client.close()

asyncio.run(test_unresolvable())
"
```

---

## Code Review Checklist

- [ ] `get_patient_by_mrn()` implements three-tier resolution (MRN → name+DOB → None)
- [ ] MRN search uses `Patient?identifier={system}|{mrn}` format
- [ ] Name+DOB fallback uses `Patient?family={name}&birthdate={dob}` format
- [ ] `PatientModel.resolution_method` set correctly (MRN / NAME_DOB / UNRESOLVED)
- [ ] `PatientModel.partial_match` set to `True` for NAME_DOB resolution
- [ ] Multiple name+DOB matches log warning but use first result
- [ ] Unresolvable patient logs warning at WARNING level (not ERROR)
- [ ] `@rate_limited` and `@circuit_breaker` decorators applied
- [ ] No PHI in logs (SEC-011)
- [ ] Docstring includes non-persistence note (AIR-012)

---

## Definition of Done Checklist

- [ ] `get_patient_by_mrn()` method added to `FHIRClient`
- [ ] `FHIR_MRN_SYSTEM` configuration added to `Settings`
- [ ] MRN search with identifier system parameter implemented
- [ ] Name+DOB fallback logic implemented
- [ ] Unresolvable patient returns `None` with warning log
- [ ] Manual validation tests (MRN hit, fallback, unresolvable) pass
- [ ] Code passes `ruff check` and `mypy` validation
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | PatientModel with resolution_method and partial_match fields |
| TASK-002 | Task | FHIRClient base implementation |
| US-016 | Story | FHIRAuthClient for OAuth authentication |

---

## Technical Notes

### Patient Resolution Three-Tier Strategy

```
┌──────────────────────────────────────────────────────────────┐
│                  Patient Resolution Flow                      │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. MRN Search                                               │
│     ┌──────────────────────────────────────┐                │
│     │ Patient?identifier={system}|{mrn}    │                │
│     └──────────────┬───────────────────────┘                │
│                    │                                         │
│         ┌──────────▼──────────┐                             │
│         │   Found (exact)?    │                             │
│         └──┬───────────────┬──┘                             │
│            │ YES           │ NO                             │
│            ▼               ▼                                 │
│     PatientModel     2. Name+DOB Fallback                   │
│     (MRN,            ┌────────────────────────────┐         │
│      partial=False)  │ Patient?family={name}&     │         │
│                      │ birthdate={dob}            │         │
│                      └────────────┬───────────────┘         │
│                                   │                          │
│                        ┌──────────▼──────────┐              │
│                        │   Found (partial)?  │              │
│                        └──┬───────────────┬──┘              │
│                           │ YES           │ NO              │
│                           ▼               ▼                  │
│                    PatientModel     3. Unresolvable         │
│                    (NAME_DOB,       ┌──────────────┐        │
│                     partial=True)   │ Log warning  │        │
│                                     │ Return None  │        │
│                                     └──────────────┘        │
└──────────────────────────────────────────────────────────────┘
```

### FHIR Search Parameters

| Resolution Method | FHIR Query | Example |
|-------------------|------------|---------|
| MRN | `Patient?identifier={system}\|{mrn}` | `Patient?identifier=http://hospital.org/mrn\|MRN-001` |
| Name+DOB | `Patient?family={name}&birthdate={dob}` | `Patient?family=Smith&birthdate=1980-01-01` |

### Agent Usage Pattern

```python
# In agent task execution:
from app.core.fhir import FHIRClient

async def process_admission(adt_event):
    fhir_client = FHIRClient()
    
    # Try MRN resolution with name+DOB fallback
    patient = await fhir_client.get_patient_by_mrn(
        mrn=adt_event.mrn,
        fallback_name=adt_event.patient_last_name,
        fallback_dob=adt_event.patient_dob,
    )
    
    if not patient:
        # Unresolvable patient — escalate to staff
        await escalate_patient_resolution_failure(adt_event)
        return
    
    if patient.partial_match:
        # Partial match — flag for manual verification
        await flag_patient_for_verification(patient)
    
    # Continue with patient data...
    medications = await fhir_client.get_medication_statements(patient.id)
```

---

## AIR-014 Compliance

| AIR-014 Requirement | Implementation |
|---------------------|----------------|
| Patient resolved via MRN in `Patient.identifier` | `Patient?identifier={system}\|{mrn}` search |
| Fallback to `Patient.name` + `birthDate` if MRN not found | `Patient?family={name}&birthdate={dob}` search |
| Unresolvable patient logs warning | `logger.warning("patient_resolution_unresolvable")` |
| Creates partial encounter | Agent-level logic (not in FHIRClient) |

---
