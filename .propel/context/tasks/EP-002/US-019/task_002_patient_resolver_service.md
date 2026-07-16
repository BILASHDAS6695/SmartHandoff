# TASK-002: Implement PatientResolver Service with Cascading Resolution Logic

> **Story:** US-019 | **Effort:** 8 hours | **Layer:** Backend  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement the core `PatientResolver` service that orchestrates patient identity resolution using a cascading strategy: MRN primary lookup → name+DOB fallback → ambiguous/unresolvable error handling. This service integrates with the FHIR client from US-017 and applies resilience wrappers from US-018.

---

## Context

Patient identity resolution is critical for all downstream agent workflows. The resolver must gracefully handle:
1. **Happy path:** MRN resolves to exactly one patient
2. **Fallback path:** MRN fails, name+DOB resolves to exactly one patient (partial match)
3. **Ambiguous path:** Name+DOB returns multiple patients (manual resolution required)
4. **Unresolvable path:** Both lookups return zero patients (partial encounter creation)

The service must be stateless, async, and integrated with existing FHIR infrastructure.

**Upstream Dependencies:**
- TASK-001: Patient models, exceptions, and query builders
- US-017: FHIR client with resilience patterns
- US-018: Circuit breaker and retry wrappers

---

## Scope

### In Scope

1. **PatientResolver Service Class:**
   - Async service with dependency injection for FHIR client
   - `resolve_patient(mrn: str, name: dict, dob: str) -> Optional[PatientModel]` method
   - Cascading resolution logic: MRN → name+DOB → error handling

2. **MRN Primary Lookup:**
   - Call `build_mrn_query()` from TASK-001
   - Execute FHIR search via `FHIRClient.search()`
   - Parse FHIR Bundle response
   - Return `PatientModel` with `resolution_method=MRN` if exactly 1 match

3. **Name+DOB Fallback Lookup:**
   - Triggered when MRN lookup returns 0 results
   - Call `build_name_dob_query()` from TASK-001
   - Execute FHIR search via `FHIRClient.search()`
   - Return `PatientModel` with `resolution_method=NAME_DOB, partial_match=True` if exactly 1 match
   - Log WARNING: "MRN lookup failed, name+DOB fallback succeeded"

4. **Ambiguous Match Detection:**
   - If name+DOB returns >1 results:
     - Raise `PatientAmbiguousError` with match count and criteria
     - Log CRITICAL with encounter ID for audit trail

5. **Unresolvable Case Handling:**
   - If both MRN and name+DOB return 0 results:
     - Return `None`
     - Issue `PatientNotFoundWarning` via logging
     - Log CRITICAL with encounter ID for clinical staff follow-up

6. **FHIR Response Parsing:**
   - Extract Patient resource from FHIR Bundle
   - Map FHIR fields to `PatientModel`
   - Handle incomplete FHIR resources gracefully

7. **Logging:**
   - All resolution attempts logged at INFO level (no PHI)
   - Fallback triggers logged at WARNING
   - Ambiguous/unresolvable logged at CRITICAL with sanitized metadata

### Out of Scope

- Care team alert dispatch (TASK-003)
- Encounter status management (TASK-003)
- Unit tests (TASK-004)
- Fuzzy name matching (future enhancement)
- Patient creation for new patients (future enhancement)

---

## Acceptance Criteria

### AC1: MRN Primary Lookup Success
**Given** a patient with MRN `"MRN-789"` exists in FHIR  
**And** the FHIR response contains exactly one Patient resource  
**When** `resolve_patient(mrn="MRN-789", name={...}, dob="...")` is called  
**Then**:
- The method returns a `PatientModel` instance
- `resolution_method` field equals `ResolutionMethod.MRN`
- `partial_match` field equals `False`
- No fallback query is executed
- INFO log entry created: "Patient resolved via MRN"

### AC2: Name+DOB Fallback Success
**Given** MRN lookup returns 0 results  
**And** name+DOB lookup returns exactly one Patient resource  
**When** `resolve_patient(mrn="MRN-INVALID", name={"family": "Smith", "given": "John"}, dob="1980-01-15")` is called  
**Then**:
- The method returns a `PatientModel` instance
- `resolution_method` field equals `ResolutionMethod.NAME_DOB`
- `partial_match` field equals `True`
- WARNING log entry created: "MRN lookup failed for MRN-INVALID, name+DOB fallback succeeded"

### AC3: Ambiguous Match Detection
**Given** MRN lookup returns 0 results  
**And** name+DOB lookup returns 3 Patient resources  
**When** `resolve_patient(mrn="MRN-INVALID", name={"family": "Smith", "given": "John"}, dob="1980-01-15")` is called  
**Then**:
- `PatientAmbiguousError` exception is raised
- Exception message includes match count: "3 patients found"
- CRITICAL log entry created with encounter context
- No `PatientModel` is returned

### AC4: Unresolvable Patient Handling
**Given** MRN lookup returns 0 results  
**And** name+DOB lookup returns 0 results  
**When** `resolve_patient(mrn="MRN-INVALID", name={"family": "Unknown", "given": "John"}, dob="2000-01-01")` is called  
**Then**:
- The method returns `None`
- `PatientNotFoundWarning` is issued via `warnings.warn()`
- CRITICAL log entry created with encounter context for follow-up

### AC5: FHIR Client Integration
**Given** the `FHIRClient` from US-017 is available  
**When** any patient lookup is performed  
**Then**:
- All FHIR API calls use the injected `FHIRClient` instance
- Circuit breaker from US-018 is applied automatically
- Retry logic from US-018 is applied automatically
- Network errors are logged and propagated as `FHIRClientError`

---

## Implementation Details

### File: `backend/app/services/patient_resolver.py`

```python
"""Patient identity resolution service with MRN and name+DOB fallback."""

import logging
import warnings
from typing import Optional
from datetime import datetime

from app.core.fhir.client import FHIRClient
from app.core.fhir.queries import build_mrn_query, build_name_dob_query
from app.core.fhir.exceptions import PatientAmbiguousError, PatientNotFoundWarning
from app.models.patient import PatientModel, ResolutionMethod
from app.core.config import settings

logger = logging.getLogger(__name__)

class PatientResolver:
    """
    Resolves patient identity from FHIR using cascading lookup strategy.
    
    Resolution order:
    1. Primary: MRN identifier lookup
    2. Fallback: Family name + DOB lookup
    3. Error handling: Ambiguous (>1 match) or Unresolvable (0 matches)
    """
    
    def __init__(self, fhir_client: Optional[FHIRClient] = None):
        """
        Initialize resolver with FHIR client dependency.
        
        Args:
            fhir_client: FHIR client instance (injected for testing, or uses singleton)
        """
        self.fhir_client = fhir_client or FHIRClient.get_instance()
    
    async def resolve_patient(
        self,
        mrn: str,
        name: dict,
        dob: str,
        encounter_id: Optional[str] = None
    ) -> Optional[PatientModel]:
        """
        Resolve patient identity using MRN primary lookup with name+DOB fallback.
        
        Args:
            mrn: Medical Record Number
            name: Dict with 'family' and 'given' keys
            dob: Date of birth in YYYY-MM-DD format
            encounter_id: Optional encounter ID for logging context
        
        Returns:
            PatientModel if resolved, None if unresolvable
        
        Raises:
            PatientAmbiguousError: If multiple patients match fallback criteria
            FHIRClientError: If FHIR API fails after retries
        
        Example:
            >>> resolver = PatientResolver()
            >>> patient = await resolver.resolve_patient(
            ...     mrn="MRN-789",
            ...     name={"family": "Smith", "given": "John"},
            ...     dob="1980-01-15"
            ... )
            >>> print(patient.resolution_method)
            'MRN'
        """
        context = {"encounter_id": encounter_id, "mrn": mrn}
        
        # Step 1: Primary MRN lookup
        logger.info(f"Attempting MRN lookup for encounter {encounter_id}")
        patient = await self._lookup_by_mrn(mrn)
        
        if patient:
            patient.resolution_method = ResolutionMethod.MRN
            patient.partial_match = False
            patient.resolved_at = datetime.utcnow()
            logger.info(f"Patient resolved via MRN for encounter {encounter_id}")
            return patient
        
        # Step 2: Fallback to name+DOB lookup
        logger.warning(
            f"MRN lookup failed for {mrn}, attempting name+DOB fallback",
            extra=context
        )
        
        patients = await self._lookup_by_name_dob(name, dob)
        
        # Step 3: Handle fallback results
        if len(patients) == 1:
            # Success: exactly one match
            patient = patients[0]
            patient.resolution_method = ResolutionMethod.NAME_DOB
            patient.partial_match = True
            patient.resolved_at = datetime.utcnow()
            logger.warning(
                f"Patient resolved via name+DOB fallback for encounter {encounter_id}",
                extra=context
            )
            return patient
        
        elif len(patients) > 1:
            # Ambiguous: multiple matches
            criteria = {"family": name.get("family"), "dob": dob, "match_count": len(patients)}
            logger.critical(
                f"Ambiguous patient match for encounter {encounter_id}: {len(patients)} patients found",
                extra={**context, **criteria}
            )
            raise PatientAmbiguousError(match_count=len(patients), criteria=criteria)
        
        else:
            # Unresolvable: zero matches
            logger.critical(
                f"Unresolvable patient for encounter {encounter_id}: no matches found",
                extra=context
            )
            warnings.warn(
                f"Patient not found for MRN {mrn} and name {name}",
                PatientNotFoundWarning
            )
            return None
    
    async def _lookup_by_mrn(self, mrn: str) -> Optional[PatientModel]:
        """
        Execute FHIR Patient search by MRN identifier.
        
        Args:
            mrn: Medical Record Number
        
        Returns:
            PatientModel if exactly 1 match, None otherwise
        """
        query = build_mrn_query(mrn, settings.FHIR_MRN_SYSTEM_URI)
        
        # Execute FHIR search (resilience wrappers applied by FHIRClient)
        bundle = await self.fhir_client.search("Patient", query)
        
        # Parse FHIR Bundle response
        patients = self._parse_fhir_bundle(bundle)
        
        # Return patient only if exactly 1 match (0 or >1 triggers fallback)
        return patients[0] if len(patients) == 1 else None
    
    async def _lookup_by_name_dob(self, name: dict, dob: str) -> list[PatientModel]:
        """
        Execute FHIR Patient search by family name and date of birth.
        
        Args:
            name: Dict with 'family' and 'given' keys
            dob: Date of birth in YYYY-MM-DD format
        
        Returns:
            List of PatientModel instances (may be empty, 1, or multiple)
        """
        family = name.get("family", "")
        given = name.get("given", "")
        
        query = build_name_dob_query(family, given, dob)
        
        # Execute FHIR search
        bundle = await self.fhir_client.search("Patient", query)
        
        # Parse FHIR Bundle response
        return self._parse_fhir_bundle(bundle)
    
    def _parse_fhir_bundle(self, bundle: dict) -> list[PatientModel]:
        """
        Parse FHIR Bundle response into PatientModel instances.
        
        Args:
            bundle: FHIR Bundle resource dict
        
        Returns:
            List of PatientModel instances
        """
        patients = []
        entries = bundle.get("entry", [])
        
        for entry in entries:
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "Patient":
                try:
                    patient = self._map_fhir_to_model(resource)
                    patients.append(patient)
                except Exception as e:
                    logger.error(f"Failed to parse FHIR Patient resource: {e}")
                    # Skip malformed resources, continue processing
        
        return patients
    
    def _map_fhir_to_model(self, fhir_resource: dict) -> PatientModel:
        """
        Map FHIR Patient resource to PatientModel.
        
        Args:
            fhir_resource: FHIR Patient resource dict
        
        Returns:
            PatientModel instance
        
        Raises:
            KeyError: If required FHIR fields are missing
        """
        # Extract MRN from identifiers
        mrn = None
        for identifier in fhir_resource.get("identifier", []):
            if identifier.get("system") == settings.FHIR_MRN_SYSTEM_URI:
                mrn = identifier.get("value")
                break
        
        # Extract name components
        name = fhir_resource.get("name", [{}])[0]
        family_name = name.get("family", "")
        given_name = name.get("given", [""])[0]
        
        # Extract date of birth
        dob = fhir_resource.get("birthDate", "")
        
        return PatientModel(
            id=fhir_resource["id"],
            mrn=mrn or "UNKNOWN",
            family_name=family_name,
            given_name=given_name,
            date_of_birth=dob,
            # resolution_method and partial_match set by caller
        )
```

### File: `backend/app/services/__init__.py`

```python
"""Service layer exports."""

from app.services.patient_resolver import PatientResolver

__all__ = ["PatientResolver"]
```

---

## Validation Steps

### Step 1: MRN Lookup Success
```bash
python -c "
import asyncio
from app.services.patient_resolver import PatientResolver

async def test():
    resolver = PatientResolver()
    patient = await resolver.resolve_patient(
        mrn='MRN-789',
        name={'family': 'Smith', 'given': 'John'},
        dob='1980-01-15',
        encounter_id='enc-001'
    )
    assert patient.resolution_method == 'MRN'
    assert patient.partial_match == False
    print('✓ MRN lookup success validated')

asyncio.run(test())
"
```

### Step 2: Name+DOB Fallback
```bash
python -c "
import asyncio
from app.services.patient_resolver import PatientResolver

async def test():
    resolver = PatientResolver()
    patient = await resolver.resolve_patient(
        mrn='MRN-INVALID',
        name={'family': 'Doe', 'given': 'Jane'},
        dob='1990-05-20',
        encounter_id='enc-002'
    )
    assert patient.resolution_method == 'NAME_DOB'
    assert patient.partial_match == True
    print('✓ Name+DOB fallback validated')

asyncio.run(test())
"
```

### Step 3: Ambiguous Match
```bash
python -c "
import asyncio
from app.services.patient_resolver import PatientResolver
from app.core.fhir.exceptions import PatientAmbiguousError

async def test():
    resolver = PatientResolver()
    try:
        await resolver.resolve_patient(
            mrn='MRN-INVALID',
            name={'family': 'Smith', 'given': 'John'},
            dob='1980-01-15',
            encounter_id='enc-003'
        )
        assert False, 'Should have raised PatientAmbiguousError'
    except PatientAmbiguousError as e:
        assert e.match_count > 1
        print(f'✓ Ambiguous match detected: {e.match_count} patients')

asyncio.run(test())
"
```

---

## Testing Strategy

### Unit Tests (Deferred to TASK-004)

Tests to be written in `backend/tests/unit/services/test_patient_resolver.py`:

1. **MRN Resolution Tests (4 tests):**
   - Test successful MRN lookup returns PatientModel with MRN resolution_method
   - Test MRN lookup with zero results triggers fallback
   - Test MRN lookup with FHIR error propagates exception
   - Test MRN lookup logs INFO on success

2. **Name+DOB Fallback Tests (4 tests):**
   - Test successful fallback returns PatientModel with NAME_DOB resolution_method
   - Test fallback with zero results returns None
   - Test fallback with multiple results raises PatientAmbiguousError
   - Test fallback logs WARNING on success

3. **Error Handling Tests (4 tests):**
   - Test ambiguous match logs CRITICAL
   - Test unresolvable patient logs CRITICAL
   - Test unresolvable patient issues PatientNotFoundWarning
   - Test FHIR client errors propagate correctly

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| FHIR server returns partial Patient resources | Medium | High | Validate required fields; log and skip malformed resources |
| Name+DOB false positives (common names) | High | Critical | Log all fallback matches at WARNING; require manual review |
| MRN system URI mismatch across environments | Medium | High | Configurable setting; validate in deployment checklist |
| Concurrent resolution requests cause race conditions | Low | Low | Service is stateless; each request independent |
| FHIR Bundle pagination not handled | Low | Medium | Document assumption: patient searches return ≤20 results (FHIR default page size) |

---

## Definition of Done

- [ ] `PatientResolver` service class implemented
- [ ] `resolve_patient()` method with MRN → name+DOB cascading logic
- [ ] MRN lookup via `_lookup_by_mrn()` private method
- [ ] Name+DOB fallback via `_lookup_by_name_dob()` private method
- [ ] Ambiguous match detection raises `PatientAmbiguousError`
- [ ] Unresolvable case returns `None` with warning
- [ ] FHIR Bundle parsing via `_parse_fhir_bundle()`
- [ ] FHIR-to-model mapping via `_map_fhir_to_model()`
- [ ] Logging at INFO, WARNING, CRITICAL levels
- [ ] Integration with `FHIRClient` from US-017
- [ ] All validation steps pass locally
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-001:** Patient models and query builders (consumed by this task)
- **TASK-003:** Encounter status management (uses resolution results)
- **TASK-004:** Unit tests (validates all resolution paths)

---

## Notes for Implementer

1. **FHIRClient Dependency:** The `FHIRClient.get_instance()` pattern assumes a singleton client. Adjust if your architecture uses dependency injection frameworks (e.g., FastAPI Depends).

2. **FHIR Bundle Pagination:** This implementation assumes patient searches return all results in a single page (FHIR default: 20 results). If pagination is needed, add a `_fetch_all_pages()` helper that follows `Bundle.link.next` URLs.

3. **Logging Context:** The `extra=context` parameter in log calls adds structured metadata for log aggregation tools (e.g., Cloud Logging). Ensure your logging config supports this.

4. **MRN Extraction:** The `_map_fhir_to_model()` method searches `Patient.identifier` array for the MRN by matching the system URI. Some EHRs use multiple identifier systems (MRN, SSN, etc.), so this logic is defensive.

5. **Async/Await:** All FHIR calls are async to support FastAPI's async request handling. Ensure your test harness (TASK-004) uses `pytest-asyncio`.

---

*Task created on 2026-07-16 for US-019 by plan-development-tasks workflow.*
