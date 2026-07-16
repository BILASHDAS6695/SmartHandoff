---
id: TASK-003
title: "Extend PharmacistAlert ORM Model — HIGH_RISK_DRUG_CLASS Alert Fields"
user_story: US-032
epic: EP-005
sprint: 2
layer: Backend / Database
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-005, US-031/TASK-006]
---

# TASK-003: Extend PharmacistAlert ORM Model — HIGH_RISK_DRUG_CLASS Alert Fields

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend / Database | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-031 (TASK-005 + TASK-006) created the `pharmacist_alerts` table and `PharmacistAlert` ORM model for drug-interaction alerts (`alert_type=PHARMACIST_ALERT`). US-032 is **additive**: the same table stores both alert types. The model requires the following new columns to support HIGH_RISK_DRUG_CLASS alerts and the pharmacist resolution workflow:

| New Column | Type | Purpose |
|---|---|---|
| `drug_class` | `VARCHAR(64)` nullable | ISMP class: `ANTICOAGULANT`, `INSULIN`, `OPIOID`, `CHEMOTHERAPY` |
| `drug_name` | `VARCHAR(255)` nullable | Single drug name (for HIGH_RISK_DRUG_CLASS alerts) |
| `status` | `ENUM` | `ACTIVE`, `RESOLVED`; default `ACTIVE` |
| `resolution_type` | `VARCHAR(64)` nullable | `REVIEWED_ACCEPTABLE`, `DOSE_ADJUSTED`, `DRUG_CHANGED`, `DISCONTINUED` |
| `resolution_note` | `TEXT` nullable | Pharmacist free-text note at resolution |
| `resolved_by_user_id` | `UUID` nullable | FK to `users.id` of resolving pharmacist |
| `resolved_at` | `TIMESTAMPTZ` nullable | UTC timestamp when alert was resolved |
| `sla_breached` | `BOOLEAN` | Default `False`; set `True` by SLA monitor (TASK-006) |

The `alert_type` enum is also extended to include `HIGH_RISK_DRUG_CLASS` alongside `PHARMACIST_ALERT`.

**Design references:**
- US-032 AC Scenario 2 — `Alert.status=RESOLVED`, `resolved_by_user_id`, `resolved_at`
- US-032 AC Scenario 3 — `sla_breached=True`
- US-032 Technical Notes — alert type is ADDITIVE; resolution types enumerated
- ADR-003 — Cloud SQL PostgreSQL 15; Alembic migrations
- ADR-007 — drug names are not PHI; no field-level encryption applied

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 1** | `alert_type=HIGH_RISK_DRUG_CLASS`, `drug_class`, `drug_name`, `severity=HIGH` persisted |
| **Scenario 2** | `status=RESOLVED`, `resolved_by_user_id`, `resolved_at`, `resolution_type` persisted |
| **Scenario 3** | `sla_breached=True` flag available for SLA monitor to set |

---

## Implementation Steps

### 1. Update `backend/app/models/pharmacist_alert.py`

Extend the existing `PharmacistAlert` model. Do not recreate the file — add only the new columns to the existing class:

```python
# --- New imports (add to existing imports block) ---
import uuid as _uuid

# --- Add to PharmacistAlert class body, after existing `created_at` column ---

    # HIGH_RISK_DRUG_CLASS alert fields
    drug_class: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="ISMP high-risk class: ANTICOAGULANT | INSULIN | OPIOID | CHEMOTHERAPY"
    )
    drug_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Single drug name triggering a HIGH_RISK_DRUG_CLASS alert"
    )

    # Resolution workflow fields (AC Scenario 2)
    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "RESOLVED", name="alert_status_enum"),
        nullable=False,
        default="ACTIVE",
        index=True,
    )
    resolution_type: Mapped[str | None] = mapped_column(
        Enum(
            "REVIEWED_ACCEPTABLE",
            "DOSE_ADJUSTED",
            "DRUG_CHANGED",
            "DISCONTINUED",
            name="alert_resolution_type_enum",
        ),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SLA monitoring (AC Scenario 3)
    sla_breached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Set True by SLA monitor when alert exceeds 24h unresolved threshold"
    )
```

Also extend the `alert_type` column's `Enum` definition to include the new value:

```python
    # Replace the existing alert_type column definition with:
    alert_type: Mapped[str] = mapped_column(
        Enum(
            "PHARMACIST_ALERT",
            "HIGH_RISK_DRUG_CLASS",
            name="alert_type_enum",
        ),
        nullable=False,
        default="PHARMACIST_ALERT",
    )
```

### 2. Update `backend/app/schemas/pharmacist_alert.py`

Add a `HighRiskDrugClassAlertCreate` schema and extend the `PharmacistAlertRead` schema:

```python
"""Extended Pydantic schemas for US-032 HIGH_RISK_DRUG_CLASS alerts.

Design refs:
    US-032 AC Scenario 1 — create payload shape
    US-032 AC Scenario 2 — resolve payload and response shape
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HighRiskDrugClassAlertCreate(BaseModel):
    """Request body for creating a HIGH_RISK_DRUG_CLASS alert.

    Used internally by the Medication Reconciliation Agent pipeline.
    """

    alert_type: Literal["HIGH_RISK_DRUG_CLASS"] = "HIGH_RISK_DRUG_CLASS"
    drug_class: str = Field(
        ...,
        pattern="^(ANTICOAGULANT|INSULIN|OPIOID|CHEMOTHERAPY)$",
        description="ISMP high-risk class identifier",
    )
    drug_name: str = Field(..., max_length=255)
    severity: Literal["HIGH"] = "HIGH"


class AlertResolveRequest(BaseModel):
    """Request body for PATCH /api/v1/alerts/{id}/resolve.

    Design ref: US-032 AC Scenario 2
    """

    resolution_type: str = Field(
        ...,
        pattern="^(REVIEWED_ACCEPTABLE|DOSE_ADJUSTED|DRUG_CHANGED|DISCONTINUED)$",
    )
    resolution_note: str | None = Field(default=None, max_length=2000)


class AlertRead(BaseModel):
    """Unified read schema for both alert types."""

    id: uuid.UUID
    encounter_id: uuid.UUID
    alert_type: str
    severity: str
    status: str
    drug_class: str | None
    drug_name: str | None
    drug_pair: list[str] | None
    interaction_description: str | None
    source: str
    sla_breached: bool
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_type: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

---

## Validation

- [ ] `PharmacistAlert` model includes all eight new columns listed in the table above
- [ ] `alert_type` enum accepts both `PHARMACIST_ALERT` and `HIGH_RISK_DRUG_CLASS`
- [ ] `status` defaults to `ACTIVE` on new alert records
- [ ] `sla_breached` defaults to `False` on new alert records
- [ ] `HighRiskDrugClassAlertCreate` rejects unknown `drug_class` values (Pydantic pattern validation)
- [ ] `AlertResolveRequest` rejects unknown `resolution_type` values

---

## Files Changed

| Action | Path |
|--------|------|
| Modify | `backend/app/models/pharmacist_alert.py` |
| Modify | `backend/app/schemas/pharmacist_alert.py` |
