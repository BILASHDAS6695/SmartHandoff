# TASK-001: Implement Patient Models, Custom Exceptions, and FHIR Query Builders

> **Story:** US-019 | **Effort:** 6 hours | **Layer:** Backend  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Establish the foundational data models, exceptions, and FHIR query builder functions required for patient identity resolution with MRN primary lookup and name+DOB fallback support.

---

## Context

Patient identity resolution requires structured data models to capture resolution metadata (how the patient was resolved, whether it was a partial match), custom exceptions for ambiguous match handling, and FHIR-compliant query builders for both MRN and name+DOB lookups. This task lays the groundwork for the PatientResolver service (TASK-002).

**Upstream Dependencies:**
- US-017: FHIR fetch infrastructure (FHIR client pattern)
- DR-024: Patient data model requirements from design.md

---

## Scope

### In Scope

1. **PatientModel Extension:**
   - Add `resolution_method: ResolutionMethod` field
   - Add `partial_match: bool` field (default: False)
   - Validate compatibility with existing Patient schema

2. **Enum Definitions:**
   - `ResolutionMethod` enum: MRN, NAME_DOB, UNRESOLVED
   - `PatientResolutionStatus` enum: RESOLVED, AMBIGUOUS, UNRESOLVED

3. **Custom Exceptions:**
   - `PatientAmbiguousError(Exception)`: Raised when multiple patients match name+DOB
   - `PatientNotFoundWarning(Warning)`: Issued when zero patients found

4. **FHIR Query Builders:**
   - `build_mrn_query(mrn: str, system_uri: str) -> str`: Constructs `Patient?identifier={system}|{mrn}`
   - `build_name_dob_query(family: str, given: str, dob: str) -> str`: Constructs `Patient?family={family}&birthdate={dob}`

5. **Configuration:**
   - Add `FHIR_MRN_SYSTEM_URI` to `Settings` in `config.py`

6. **Encounter Model Update:**
   - Add `patient_resolution_status: PatientResolutionStatus` field to `Encounter` model

### Out of Scope

- PatientResolver service logic (TASK-002)
- Care team alert dispatch (TASK-003)
- Unit tests (TASK-004)

---

## Acceptance Criteria

### AC1: PatientModel Extension
**Given** the existing `PatientModel` in `backend/app/models/patient.py`  
**When** the model is extended with resolution metadata fields  
**Then** the model includes:
- `resolution_method: ResolutionMethod` field
- `partial_match: bool` field with default `False`
- All existing fields remain unchanged

### AC2: Enum Definitions
**Given** patient resolution requires status tracking  
**When** enums are defined in `backend/app/models/patient.py`  
**Then**:
- `ResolutionMethod` enum has values: MRN, NAME_DOB, UNRESOLVED
- `PatientResolutionStatus` enum has values: RESOLVED, AMBIGUOUS, UNRESOLVED

### AC3: Custom Exceptions
**Given** ambiguous and unresolvable patient scenarios  
**When** exceptions are defined in `backend/app/core/fhir/exceptions.py`  
**Then**:
- `PatientAmbiguousError` exception class exists with informative message
- `PatientNotFoundWarning` warning class exists for logging

### AC4: FHIR Query Builders
**Given** MRN and name+DOB lookup requirements  
**When** query builders are implemented in `backend/app/core/fhir/queries.py`  
**Then**:
- `build_mrn_query("MRN-789", "http://hospital.org/mrn")` returns `"Patient?identifier=http://hospital.org/mrn|MRN-789"`
- `build_name_dob_query("Smith", "John", "1980-01-15")` returns `"Patient?family=Smith&given=John&birthdate=1980-01-15"`
- Query strings are URL-encoded for special characters

### AC5: Configuration Setting
**Given** MRN system URIs vary by hospital  
**When** `FHIR_MRN_SYSTEM_URI` is added to `Settings`  
**Then**:
- Setting has default value: `"http://hospital.org/mrn"`
- Setting is environment-variable configurable
- Setting includes docstring explaining usage

### AC6: Encounter Model Update
**Given** encounters must track patient resolution status  
**When** `Encounter` model is updated  
**Then**:
- `patient_resolution_status: PatientResolutionStatus` field exists
- Field defaults to `RESOLVED`
- Field is indexed for query performance

---

## Implementation Details

### File: `backend/app/models/patient.py`

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ResolutionMethod(str, Enum):
    """Method used to resolve patient identity."""
    MRN = "MRN"
    NAME_DOB = "NAME_DOB"
    UNRESOLVED = "UNRESOLVED"

class PatientResolutionStatus(str, Enum):
    """Status of patient identity resolution."""
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"

class PatientModel(BaseModel):
    """Patient data model with FHIR identity resolution metadata."""
    
    # Existing fields (example - adjust to actual schema)
    id: str
    mrn: str
    family_name: str
    given_name: str
    date_of_birth: str
    # ... other existing fields ...
    
    # New resolution metadata fields
    resolution_method: ResolutionMethod = Field(
        default=ResolutionMethod.MRN,
        description="Method used to resolve patient identity (MRN, NAME_DOB, or UNRESOLVED)"
    )
    partial_match: bool = Field(
        default=False,
        description="True if patient was resolved via fallback method (name+DOB)"
    )
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when patient identity was resolved"
    )
    
    class Config:
        use_enum_values = True
```

### File: `backend/app/core/fhir/exceptions.py`

Extend existing file with patient-specific exceptions:

```python
# ... existing FHIR exceptions ...

class PatientAmbiguousError(Exception):
    """
    Raised when multiple patients match the resolution criteria.
    Requires manual intervention to disambiguate.
    """
    def __init__(self, match_count: int, criteria: dict):
        self.match_count = match_count
        self.criteria = criteria
        message = (
            f"Ambiguous patient match: {match_count} patients found for criteria {criteria}. "
            "Manual resolution required."
        )
        super().__init__(message)

class PatientNotFoundWarning(Warning):
    """
    Warning issued when no patients match the resolution criteria.
    Allows partial encounter creation.
    """
    pass
```

### File: `backend/app/core/fhir/queries.py`

New file for FHIR query builders:

```python
"""FHIR Patient search query builders."""

from urllib.parse import quote

def build_mrn_query(mrn: str, system_uri: str) -> str:
    """
    Build FHIR Patient search query by MRN identifier.
    
    Args:
        mrn: Medical Record Number
        system_uri: FHIR identifier system URI (e.g., "http://hospital.org/mrn")
    
    Returns:
        FHIR search query string (e.g., "Patient?identifier=http://hospital.org/mrn|MRN-789")
    
    Example:
        >>> build_mrn_query("MRN-789", "http://hospital.org/mrn")
        'Patient?identifier=http://hospital.org/mrn|MRN-789'
    """
    # URL-encode system URI to handle special characters
    encoded_system = quote(system_uri, safe='')
    encoded_mrn = quote(mrn, safe='')
    return f"Patient?identifier={encoded_system}|{encoded_mrn}"

def build_name_dob_query(family: str, given: str, dob: str) -> str:
    """
    Build FHIR Patient search query by name and date of birth.
    
    Args:
        family: Family (last) name
        given: Given (first) name
        dob: Date of birth in YYYY-MM-DD format
    
    Returns:
        FHIR search query string (e.g., "Patient?family=Smith&given=John&birthdate=1980-01-15")
    
    Example:
        >>> build_name_dob_query("Smith", "John", "1980-01-15")
        'Patient?family=Smith&given=John&birthdate=1980-01-15'
    """
    # URL-encode names to handle special characters (e.g., O'Brien)
    encoded_family = quote(family, safe='')
    encoded_given = quote(given, safe='')
    # Date format should already be YYYY-MM-DD, but validate
    if not _is_valid_date_format(dob):
        raise ValueError(f"Invalid date format: {dob}. Expected YYYY-MM-DD.")
    
    return f"Patient?family={encoded_family}&given={encoded_given}&birthdate={dob}"

def _is_valid_date_format(date_str: str) -> bool:
    """Validate date string is in YYYY-MM-DD format."""
    from datetime import datetime
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False
```

### File: `backend/app/core/config.py`

Add FHIR MRN system URI setting:

```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # FHIR Patient Resolution
    FHIR_MRN_SYSTEM_URI: str = Field(
        default="http://hospital.org/mrn",
        description="FHIR identifier system URI for Medical Record Number (MRN). "
                    "This varies by hospital and EHR vendor."
    )
    
    class Config:
        env_file = ".env"
        case_sensitive = True
```

### File: `backend/app/models/encounter.py`

Add patient resolution status field:

```python
from sqlalchemy import Column, String, Enum as SQLEnum
from app.models.patient import PatientResolutionStatus

class Encounter(Base):
    __tablename__ = "encounters"
    
    # ... existing fields ...
    
    patient_resolution_status = Column(
        SQLEnum(PatientResolutionStatus),
        default=PatientResolutionStatus.RESOLVED,
        nullable=False,
        index=True,  # Index for query performance
        comment="Status of patient identity resolution (RESOLVED, AMBIGUOUS, UNRESOLVED)"
    )
```

---

## Validation Steps

### Step 1: Model Validation
```bash
# Run Python to validate model instantiation
python -c "
from app.models.patient import PatientModel, ResolutionMethod

# Test model with resolution metadata
patient = PatientModel(
    id='123',
    mrn='MRN-789',
    family_name='Smith',
    given_name='John',
    date_of_birth='1980-01-15',
    resolution_method=ResolutionMethod.MRN,
    partial_match=False
)
print(f'✓ PatientModel validated: {patient.resolution_method}')
"
```

### Step 2: Exception Validation
```bash
python -c "
from app.core.fhir.exceptions import PatientAmbiguousError

try:
    raise PatientAmbiguousError(3, {'family': 'Smith', 'dob': '1980-01-15'})
except PatientAmbiguousError as e:
    print(f'✓ PatientAmbiguousError raised: {e}')
"
```

### Step 3: Query Builder Validation
```bash
python -c "
from app.core.fhir.queries import build_mrn_query, build_name_dob_query

mrn_query = build_mrn_query('MRN-789', 'http://hospital.org/mrn')
name_query = build_name_dob_query('Smith', 'John', '1980-01-15')

assert 'identifier=' in mrn_query
assert 'family=Smith' in name_query
print(f'✓ Query builders validated')
print(f'  MRN query: {mrn_query}')
print(f'  Name query: {name_query}')
"
```

---

## Testing Strategy

### Unit Tests (Deferred to TASK-004)

Tests to be written in `backend/tests/unit/models/test_patient.py`:
- Test `PatientModel` instantiation with resolution metadata
- Test `ResolutionMethod` enum values
- Test `PatientResolutionStatus` enum values

Tests to be written in `backend/tests/unit/core/fhir/test_queries.py`:
- Test `build_mrn_query()` with various MRN formats
- Test `build_name_dob_query()` with special characters (e.g., O'Brien)
- Test URL encoding in query strings
- Test date format validation

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PatientModel schema conflicts with existing code | Medium | High | Review all references to Patient model before adding fields |
| MRN system URI differs across environments | High | Medium | Use environment-variable configuration; document in deployment guide |
| URL encoding breaks FHIR server parsing | Low | Medium | Test query builders against actual FHIR test server |
| Encounter model migration breaks production | Low | Critical | Create Alembic migration script; test in staging first |

---

## Definition of Done

- [ ] `PatientModel` extended with `resolution_method` and `partial_match` fields
- [ ] `ResolutionMethod` and `PatientResolutionStatus` enums defined
- [ ] `PatientAmbiguousError` and `PatientNotFoundWarning` exceptions created
- [ ] `build_mrn_query()` and `build_name_dob_query()` functions implemented
- [ ] `FHIR_MRN_SYSTEM_URI` setting added to `config.py`
- [ ] `Encounter` model updated with `patient_resolution_status` field
- [ ] Alembic migration script created for Encounter table change
- [ ] All validation steps pass locally
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-002:** PatientResolver service (consumes query builders)
- **TASK-003:** Encounter status management (uses patient_resolution_status)
- **TASK-004:** Unit tests (validates all models and exceptions)

---

## Notes for Implementer

1. **Existing Patient Model:** Check if `PatientModel` already exists or if you need to create it. The example above assumes a Pydantic model; adjust if using SQLAlchemy ORM models directly.

2. **Database Migration:** The `Encounter` model change requires an Alembic migration. Generate it with:
   ```bash
   alembic revision --autogenerate -m "Add patient_resolution_status to encounters"
   ```

3. **URL Encoding:** The `urllib.parse.quote()` function handles special characters in names (e.g., O'Brien → O%27Brien). The FHIR server will decode these automatically.

4. **Date Validation:** The `_is_valid_date_format()` helper ensures dates are in FHIR-compliant YYYY-MM-DD format before constructing queries.

5. **Enum Values:** Using `use_enum_values = True` in Pydantic Config ensures enums serialize to strings ("MRN") rather than objects (ResolutionMethod.MRN) in JSON responses.

---

*Task created on 2026-07-16 for US-019 by plan-development-tasks workflow.*
