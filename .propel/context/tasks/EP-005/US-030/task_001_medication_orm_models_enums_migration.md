# TASK-001: Medication ORM Models, Enums, and Alembic Migration

> **Story:** US-030 | **Effort:** 6 hours | **Layer:** Backend — Data Layer  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Define the SQLAlchemy ORM model for the `medication` table with all reconciliation fields, create supporting enums, and generate the Alembic migration so the schema is ready before agent logic is implemented.

---

## Context

The medication reconciliation agent (TASK-004) stores per-drug comparison results in the `medication` table. This task creates the canonical data contract (model + enums) that all downstream tasks depend on. Without this foundation, TASK-002 through TASK-005 cannot persist or query reconciliation results.

**Upstream Dependencies:**
- US-006: Existing `medication` ORM baseline model
- DR-xxx: Data architecture requirements from `design.md` (PostgreSQL 15, SQLAlchemy 2.x, CMEK at ORM layer)

---

## Scope

### In Scope

1. **Reconciliation Enums** — `backend/app/models/medication.py`:
   - `ReconciliationCategory`: `CONTINUED`, `NEW`, `STOPPED`, `DOSE_CHANGED`
   - `ReconciliationFlag`: `DUPLICATE`, `STOPPED_WITHOUT_ORDER`
   - `MedicationListSource`: `PRE_ADMIT`, `INPATIENT`, `DISCHARGE`

2. **`Medication` ORM Model Extension** — `backend/app/models/medication.py`:
   - `rxnorm_cui: str | None` — RxNorm Concept Unique Identifier
   - `reconciliation_category: ReconciliationCategory | None`
   - `flags: list[ReconciliationFlag]` — stored as `ARRAY` column
   - `dose_value: float | None` and `dose_unit: str | None` — parsed dose
   - `route: str | None`
   - `frequency: str | None`
   - `sources: list[MedicationListSource]` — which lists drug appears on
   - `encounter_id: UUID` — FK → `encounters.id`
   - `reconciliation_completed_at: datetime | None`

3. **`MedicationReconciliationResult` Pydantic schema** — `backend/app/schemas/medication.py`:
   - Response schema for `GET /api/v1/encounters/{id}/medications/reconciliation`
   - Fields: `id`, `name`, `rxnorm_cui`, `reconciliation_category`, `pre_admit`, `inpatient`, `discharge` (bool each), `flags`, `dose`, `route`, `frequency`

4. **Alembic migration** — `backend/alembic/versions/xxxx_add_medication_reconciliation_fields.py`

### Out of Scope

- FHIR fetching logic (TASK-002)
- RxNorm normalisation calls (TASK-003)
- Reconciliation comparison algorithm (TASK-004)
- API endpoint (TASK-005)
- Unit tests (TASK-006)

---

## Acceptance Criteria

### AC1: Enums Defined
**Given** the medication reconciliation domain requires categorisation  
**When** `ReconciliationCategory`, `ReconciliationFlag`, and `MedicationListSource` enums are defined  
**Then**:
- `ReconciliationCategory` has values: `CONTINUED`, `NEW`, `STOPPED`, `DOSE_CHANGED`
- `ReconciliationFlag` has values: `DUPLICATE`, `STOPPED_WITHOUT_ORDER`
- `MedicationListSource` has values: `PRE_ADMIT`, `INPATIENT`, `DISCHARGE`

### AC2: ORM Model Extended
**Given** the existing `Medication` ORM model  
**When** reconciliation fields are added  
**Then** the model includes all fields listed in scope with correct column types and nullable constraints

### AC3: Pydantic Response Schema
**Given** the API endpoint returns reconciliation results  
**When** `MedicationReconciliationResult` is instantiated with valid data  
**Then** it serialises to a JSON object with `pre_admit`, `inpatient`, `discharge` boolean fields and a `flags` array

### AC4: Alembic Migration
**Given** the ORM model changes are complete  
**When** `alembic upgrade head` is run  
**Then** the migration applies without error, new columns exist in `medication` table, and `alembic downgrade -1` rolls back cleanly

---

## Implementation Details

### File: `backend/app/models/medication.py`

```python
"""Medication ORM model with FHIR reconciliation fields."""

from enum import Enum
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class ReconciliationCategory(str, Enum):
    """Three-way medication reconciliation outcome category."""
    CONTINUED = "CONTINUED"
    NEW = "NEW"
    STOPPED = "STOPPED"
    DOSE_CHANGED = "DOSE_CHANGED"


class ReconciliationFlag(str, Enum):
    """Special alert flags raised during reconciliation."""
    DUPLICATE = "DUPLICATE"
    STOPPED_WITHOUT_ORDER = "STOPPED_WITHOUT_ORDER"


class MedicationListSource(str, Enum):
    """FHIR list from which a medication was sourced."""
    PRE_ADMIT = "PRE_ADMIT"
    INPATIENT = "INPATIENT"
    DISCHARGE = "DISCHARGE"


class Medication(Base):
    __tablename__ = "medication"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encounter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False, comment="Display drug name from FHIR")
    rxnorm_cui = Column(String(20), nullable=True, index=True, comment="RxNorm CUI from RxNav")
    reconciliation_category = Column(
        SQLEnum(ReconciliationCategory),
        nullable=True,
        index=True,
        comment="CONTINUED | NEW | STOPPED | DOSE_CHANGED",
    )
    flags = Column(
        ARRAY(SQLEnum(ReconciliationFlag, name="reconciliationflag")),
        nullable=False,
        server_default="{}",
        comment="DUPLICATE, STOPPED_WITHOUT_ORDER flags",
    )
    dose_value = Column(Float, nullable=True, comment="Parsed numeric dose value")
    dose_unit = Column(String(20), nullable=True, comment="Dose unit e.g. mg")
    route = Column(String(50), nullable=True)
    frequency = Column(String(50), nullable=True)
    sources = Column(
        ARRAY(SQLEnum(MedicationListSource, name="medicationlistsource")),
        nullable=False,
        server_default="{}",
        comment="Which FHIR lists this drug appears on",
    )
    reconciliation_completed_at = Column(DateTime(timezone=True), nullable=True)

    encounter = relationship("Encounter", back_populates="medications")
```

### File: `backend/app/schemas/medication.py`

```python
"""Pydantic schemas for medication reconciliation API responses."""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from app.models.medication import ReconciliationCategory, ReconciliationFlag


class MedicationReconciliationResult(BaseModel):
    """Per-drug reconciliation result returned by the API."""

    id: UUID
    name: str
    rxnorm_cui: Optional[str] = None
    reconciliation_category: Optional[ReconciliationCategory] = None
    pre_admit: bool = Field(description="True if drug was on pre-admission list")
    inpatient: bool = Field(description="True if drug was on inpatient list")
    discharge: bool = Field(description="True if drug is on discharge list")
    flags: list[ReconciliationFlag] = Field(default_factory=list)
    dose: Optional[str] = Field(default=None, description="Human-readable dose string e.g. 500mg")
    route: Optional[str] = None
    frequency: Optional[str] = None

    model_config = {"from_attributes": True}


class MedicationReconciliationResponse(BaseModel):
    """Full reconciliation response for an encounter."""

    encounter_id: UUID
    total_medications: int
    reconciliation_completed_at: Optional[str] = None
    medications: list[MedicationReconciliationResult]
```

### File: `backend/alembic/versions/xxxx_add_medication_reconciliation_fields.py`

Generate with:
```bash
cd backend
alembic revision --autogenerate -m "add_medication_reconciliation_fields"
```

Verify the generated migration includes:
- `ADD COLUMN rxnorm_cui VARCHAR(20)`
- `ADD COLUMN reconciliation_category reconciliationcategory`
- `ADD COLUMN flags reconciliationflag[] NOT NULL DEFAULT '{}'`
- `ADD COLUMN dose_value FLOAT`
- `ADD COLUMN dose_unit VARCHAR(20)`
- `ADD COLUMN route VARCHAR(50)`
- `ADD COLUMN frequency VARCHAR(50)`
- `ADD COLUMN sources medicationlistsource[] NOT NULL DEFAULT '{}'`
- `ADD COLUMN reconciliation_completed_at TIMESTAMPTZ`

---

## Validation Steps

### Step 1: Enum Validation
```bash
python -c "
from app.models.medication import ReconciliationCategory, ReconciliationFlag, MedicationListSource
assert len(ReconciliationCategory) == 4
assert len(ReconciliationFlag) == 2
assert len(MedicationListSource) == 3
print('✓ All enums validated')
"
```

### Step 2: Schema Serialisation
```bash
python -c "
import uuid
from app.schemas.medication import MedicationReconciliationResult
from app.models.medication import ReconciliationCategory, ReconciliationFlag

result = MedicationReconciliationResult(
    id=uuid.uuid4(),
    name='Metformin 500mg oral',
    rxnorm_cui='860975',
    reconciliation_category=ReconciliationCategory.CONTINUED,
    pre_admit=True,
    inpatient=True,
    discharge=True,
    flags=[],
    dose='500mg',
    route='oral',
    frequency='twice daily',
)
print(result.model_dump_json(indent=2))
print('✓ Schema serialised correctly')
"
```

### Step 3: Migration Apply/Rollback
```bash
cd backend
alembic upgrade head
echo "✓ Migration applied"
alembic downgrade -1
echo "✓ Migration rolled back"
alembic upgrade head
echo "✓ Migration re-applied for dev"
```

---

## Testing Strategy

Unit tests are deferred to TASK-006. Validate locally using the steps above.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Existing `medication` table has incompatible schema | Medium | High | Review US-006 ORM baseline before extending; add nullable=True to new columns |
| PostgreSQL ARRAY type not supported by test DB | Low | Medium | Use `postgresql+asyncpg` in test; mock ARRAY columns if SQLite used for unit tests |
| Enum name collisions with existing DB types | Low | Medium | Prefix enum type names: `reconciliationcategory`, `reconciliationflag`, `medicationlistsource` |

---

## Definition of Done

- [ ] `ReconciliationCategory`, `ReconciliationFlag`, `MedicationListSource` enums defined
- [ ] `Medication` ORM model extended with all reconciliation columns
- [ ] `MedicationReconciliationResult` and `MedicationReconciliationResponse` Pydantic schemas created
- [ ] Alembic migration generated and tested (up + down)
- [ ] All validation steps pass locally
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-002:** FHIR Medication Fetcher (populates `sources` field)
- **TASK-003:** RxNorm Normalisation (populates `rxnorm_cui` field)
- **TASK-004:** Reconciliation Agent (populates `reconciliation_category` and `flags`)
- **TASK-005:** FastAPI endpoint (reads `MedicationReconciliationResult` schema)

---

## Notes for Implementer

1. **ARRAY columns** — PostgreSQL-specific; when writing unit tests use `postgresql+asyncpg` DSN or abstract with repository pattern mocks.
2. **Enum creation order** — SQLAlchemy `CREATE TYPE` statements must precede `ALTER TABLE`. Alembic autogenerate handles this, but verify the migration file.
3. **Existing model** — If `Medication` already has any of these columns from US-006, skip those additions and only add missing ones.
4. **PHI encryption** — Drug names are not PHI per se, but `encounter_id` is a link to PHI. Apply field-level encryption if org policy requires (ADR-007).

---

*Task created on 2026-07-16 for US-030 by plan-development-tasks workflow.*
