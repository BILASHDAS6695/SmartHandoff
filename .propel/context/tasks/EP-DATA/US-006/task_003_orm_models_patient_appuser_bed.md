---
id: TASK-003
title: "Define ORM Models — `Patient`, `AppUser`, and `Bed`"
user_story: US-006
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Define ORM Models — `Patient`, `AppUser`, and `Bed`

> **Story:** US-006 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This task defines the first three of ten SQLAlchemy ORM models. These models represent:

- **`Patient`** — the central entity holding all PHI; uses `EncryptedString` and `DeterministicEncryptedString` TypeDecorators from US-007; enforces MRN uniqueness via a unique index on the deterministically-encrypted `mrn_encrypted` column (DR-002, DR-020).
- **`AppUser`** — staff accounts managed by the identity provider; used by RBAC middleware to resolve role claims (SEC-002, AIR-031).
- **`Bed`** — hospital bed inventory managed by the Bed Management Agent; used by the bed board materialised view (DR-007, FR-040).

> **Dependency on US-007**: The `EncryptedString` and `DeterministicEncryptedString` TypeDecorators are implemented in US-007. This task declares `from app.db.encryption import EncryptedString, DeterministicEncryptedString` as an import. If US-007 is not yet complete, a stub encryption module must be in place (see Implementation Step 1).

---

## Acceptance Criteria Addressed

| US-006 AC | Requirement |
|---|---|
| **Scenario 3** | MRN unique constraint: `Patient.mrn_encrypted` must carry a `unique=True` constraint enabling the DB to reject duplicate MRNs |
| **Scenario 4** | Soft delete: `Patient` inherits `SoftDeleteMixin`; `deleted_at` column present |
| **DoD** | ORM models defined for `patient`, `app_user`, `bed` tables with correct column types, relationships, and constraints |

---

## Implementation Steps

### 1. Create Encryption Stub (if US-007 is not yet merged)

If `backend/app/db/encryption.py` does not yet exist, create a stub that allows this task to proceed without US-007:

```python
# backend/app/db/encryption.py — STUB (replace with US-007 full implementation)
"""Stub PHI encryption TypeDecorators.

Replace this file with the full US-007 implementation before deploying to any environment.
"""
import sqlalchemy as sa
from sqlalchemy.engine import Dialect


class EncryptedString(sa.TypeDecorator):
    """Stub: stores plaintext. Replace with AES-256-GCM implementation (US-007)."""
    impl = sa.Text
    cache_ok = True

    def process_bind_processor(self, dialect: Dialect):
        return lambda value: value  # No-op stub

    def process_result_processor(self, dialect: Dialect, coltype):
        return lambda value: value  # No-op stub


class DeterministicEncryptedString(EncryptedString):
    """Stub: deterministic variant for MRN uniqueness. Replace with US-007."""
    pass
```

This stub must be replaced by the full US-007 implementation before any PHI is written to the database. Mark this with a `# TODO(US-007): Replace stub with AES-256-GCM implementation` comment.

### 2. Author `backend/app/models/patient.py`

```python
"""Patient ORM model.

PHI columns use TypeDecorators from US-007 (AES-256-GCM encryption).
DR-002: PHI fields encrypted at rest.
DR-005: Soft deletes — `deleted_at` via SoftDeleteMixin.
DR-020: MRN deduplication via unique constraint on deterministic ciphertext.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.encryption import DeterministicEncryptedString, EncryptedString
from app.db.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    """Represents a hospital patient.

    All PHI fields are encrypted at the ORM layer using AES-256-GCM (US-007).
    The `mrn_encrypted` column uses deterministic encryption to support the
    unique index required for MRN deduplication (DR-020).
    """

    __tablename__ = "patient"

    # Primary key — UUID v4, generated application-side
    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # PHI fields — encrypted via US-007 TypeDecorators (DR-002)
    first_name: Mapped[str] = mapped_column(EncryptedString(255), nullable=False)
    last_name: Mapped[str] = mapped_column(EncryptedString(255), nullable=False)
    date_of_birth: Mapped[str] = mapped_column(
        EncryptedString(64),
        nullable=False,
        comment="Stored as ISO-8601 string (YYYY-MM-DD) then encrypted",
    )
    phone: Mapped[str | None] = mapped_column(EncryptedString(64), nullable=True)
    email: Mapped[str | None] = mapped_column(EncryptedString(255), nullable=True)

    # MRN uses deterministic encryption to support unique constraint (DR-020)
    mrn_encrypted: Mapped[str] = mapped_column(
        DeterministicEncryptedString(128),
        nullable=False,
        unique=True,  # DB-enforced uniqueness; same plaintext → same ciphertext
        comment="Medical Record Number — deterministically encrypted for unique indexing",
    )

    # Non-PHI fields
    language_code: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        server_default="en",
        comment="IETF BCP 47 language tag (e.g., en, es, fr) for document generation",
    )

    # Relationships
    encounters: Mapped[list["Encounter"]] = relationship(
        "Encounter",
        back_populates="patient",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_patient_mrn_encrypted", "mrn_encrypted", unique=True),
        sa.Index("ix_patient_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<Patient id={self.id} mrn=[ENCRYPTED]>"
```

### 3. Author `backend/app/models/app_user.py`

```python
"""AppUser ORM model — staff accounts managed by the Identity Provider.

Users are provisioned via SCIM 2.0 (AIR-032). Role claims arrive in JWT
and are validated against this table by RBAC middleware (SEC-002, AIR-031).
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class UserRole(str, sa.Enum):
    """Staff role enumeration matching RBAC permission matrix (design.md §8.3)."""
    ADMIN = "admin"
    PHYSICIAN = "physician"
    NURSE = "nurse"
    PHARMACIST = "pharmacist"
    BED_MANAGER = "bed_manager"


class AppUser(Base, TimestampMixin):
    """Staff user account.

    Created/updated by SCIM 2.0 provisioning endpoint (AIR-032).
    Deprovisioning sets `is_active=False` and invalidates JWT via Redis blocklist.
    """

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Identity provider subject claim (`sub` in JWT)
    idp_subject: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        unique=True,
        comment="OIDC `sub` claim from Identity Provider; used to resolve user on login",
    )

    email: Mapped[str] = mapped_column(
        sa.String(320),  # RFC 5321 max email length
        nullable=False,
        unique=True,
    )

    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    role: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        comment="One of: admin, physician, nurse, pharmacist, bed_manager",
    )

    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        comment="Set to False on SCIM deprovisioning (AIR-032)",
    )

    unit: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="Hospital unit assignment for nurses (scopes patient list access)",
    )

    __table_args__ = (
        sa.Index("ix_app_user_idp_subject", "idp_subject", unique=True),
        sa.Index("ix_app_user_email", "email", unique=True),
        sa.Index("ix_app_user_role_active", "role", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<AppUser id={self.id} role={self.role} active={self.is_active}>"
```

### 4. Author `backend/app/models/bed.py`

```python
"""Bed ORM model — hospital bed inventory managed by the Bed Management Agent.

Used by the `mv_bed_board` materialised view (DR-007, FR-040–FR-043).
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class BedStatus(str):
    """Bed occupancy status constants."""
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    CLEANING = "cleaning"
    MAINTENANCE = "maintenance"
    BLOCKED = "blocked"


class Bed(Base, TimestampMixin):
    """Hospital bed record.

    The Bed Management Agent updates `status` and `predicted_discharge_at`
    based on ADT events and ML inference (FR-040–FR-043).
    """

    __tablename__ = "bed"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    bed_number: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        comment="Human-readable bed identifier (e.g., '4B-12')",
    )

    unit: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment="Hospital unit (e.g., 'ICU', 'Cardiology', 'ED')",
    )

    ward: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="available",
        comment="One of: available, occupied, cleaning, maintenance, blocked",
    )

    # Optional FK to current encounter (nullable — bed may be unoccupied)
    current_encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="SET NULL"),
        nullable=True,
    )

    predicted_discharge_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="ML-predicted discharge time for bed board planning (FR-042)",
    )

    __table_args__ = (
        sa.UniqueConstraint("unit", "bed_number", name="uq_bed_unit_number"),
        sa.Index("ix_bed_unit_status", "unit", "status"),
    )

    def __repr__(self) -> str:
        return f"<Bed {self.unit}/{self.bed_number} status={self.status}>"
```

### 5. Update `backend/app/models/__init__.py`

```python
from app.models.app_user import AppUser
from app.models.bed import Bed
from app.models.patient import Patient

__all__ = ["AppUser", "Bed", "Patient"]
```

---

## Definition of Done

- [ ] `backend/app/models/patient.py` defines `Patient` model with all PHI fields using `EncryptedString` / `DeterministicEncryptedString`
- [ ] `Patient.mrn_encrypted` column has `unique=True` and an explicit `Index("ix_patient_mrn_encrypted", "mrn_encrypted", unique=True)`
- [ ] `Patient` inherits both `TimestampMixin` and `SoftDeleteMixin`
- [ ] `backend/app/models/app_user.py` defines `AppUser` with `idp_subject` unique constraint and `is_active` flag
- [ ] `backend/app/models/bed.py` defines `Bed` with `UniqueConstraint("unit", "bed_number")` and `Index("ix_bed_unit_status")`
- [ ] If US-007 not yet complete: `backend/app/db/encryption.py` stub exists with `# TODO(US-007)` marker
- [ ] `backend/app/models/__init__.py` exports all three models
- [ ] No PHI values hardcoded in any model file (field definitions only; no test data)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-002 | Preceding task | `Base`, `TimestampMixin`, `SoftDeleteMixin` must be defined |
| US-007 | Story (parallel) | `EncryptedString` / `DeterministicEncryptedString` TypeDecorators; stub acceptable until US-007 merges |

---

## Files Modified

| File | Action |
|---|---|
| `backend/app/db/encryption.py` | Create (stub if US-007 not merged) |
| `backend/app/models/patient.py` | Create |
| `backend/app/models/app_user.py` | Create |
| `backend/app/models/bed.py` | Create |
| `backend/app/models/__init__.py` | Update (add exports) |
