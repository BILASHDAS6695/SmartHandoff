---
id: TASK-005
title: "Pharmacist Alert Endpoint — POST /api/v1/encounters/{id}/alerts"
user_story: US-031
epic: EP-005
sprint: 2
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-004]
---

# TASK-005: Pharmacist Alert Endpoint — POST /api/v1/encounters/{id}/alerts

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 4 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task creates the `POST /api/v1/encounters/{id}/alerts` FastAPI endpoint that:

1. Accepts a pharmacist alert payload (severity, drug pair, description, source, metadata).
2. Persists the alert to PostgreSQL via the `PharmacistAlert` ORM model.
3. Sets `interaction_check_status` on the `MedicationReconciliation` record (either `COMPLETE` or `INCOMPLETE`).
4. Publishes a Pub/Sub message to the `notification-requests` topic with `priority=IMMEDIATE` for `HIGH`-severity alerts and `priority=STANDARD` for all others.
5. Returns HTTP 201 with the created alert.

Role enforcement: only `PHARMACIST` and `ADMIN` roles may call this endpoint (RBAC, design.md §3.3).

**Design references:**
- design.md §3.3 — FastAPI router: `/api/v1/encounters`; JWT + RBAC middleware
- US-031 AC Scenario 1 — alert persisted; appears in dashboard within 60 s
- US-031 AC Scenario 4 — MEDIUM alert with INCOMPLETE status
- US-031 Technical Notes — HIGH alert → `IMMEDIATE` Pub/Sub priority
- ADR-001 — all events published to GCP Pub/Sub before side-effects

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | `PHARMACIST_ALERT` created with `severity=HIGH`; Pub/Sub `priority=IMMEDIATE` |
| AC Scenario 4 | `interaction_check_status=INCOMPLETE`; MEDIUM alert published |

---

## Implementation Steps

### 1. Add ORM model `backend/app/models/pharmacist_alert.py`

```python
"""SQLAlchemy model for pharmacist drug-interaction alerts.

Design refs:
    US-031 AC Scenario 1 — severity, drug_pair, interaction_description, source
    US-031 AC Scenario 4 — interaction_check_status persisted on reconciliation
    ADR-007              — PHI fields encrypted at ORM layer (drug names are not PHI)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PharmacistAlert(Base):
    """Represents a pharmacist-facing drug interaction alert.

    Attributes:
        id: UUID primary key.
        encounter_id: FK to the encounter that triggered the alert.
        alert_type: Always ``PHARMACIST_ALERT``.
        severity: ``HIGH``, ``MEDIUM``, or ``LOW``.
        drug_pair: JSON array of two drug names, e.g. ``["Warfarin","Aspirin"]``.
        interaction_description: Free-text description from RxNav or OpenFDA.
        source: ``RXNAV``, ``OPENFDA``, or ``SYSTEM`` (degradation alert).
        interaction_check_status: ``COMPLETE`` or ``INCOMPLETE``.
        metadata_: Additional source-specific metadata dict.
        created_at: UTC timestamp of alert creation.
    """

    __tablename__ = "pharmacist_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="PHARMACIST_ALERT"
    )
    severity: Mapped[str] = mapped_column(
        Enum("HIGH", "MEDIUM", "LOW", name="alert_severity_enum"),
        nullable=False,
    )
    drug_pair: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    interaction_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="RXNAV")
    interaction_check_status: Mapped[str] = mapped_column(
        Enum("COMPLETE", "INCOMPLETE", name="check_status_enum"),
        nullable=False,
        default="COMPLETE",
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
```

### 2. Add Pydantic schemas `backend/app/schemas/pharmacist_alert.py`

```python
"""Pydantic schemas for pharmacist alert create/read operations.

Design refs:
    US-031 AC Scenario 1 — request/response shape
    design.md §4.1        — Pydantic v2; FastAPI OpenAPI generation
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PharmacistAlertCreate(BaseModel):
    """Request body for ``POST /api/v1/encounters/{id}/alerts``."""

    alert_type: str = Field(default="PHARMACIST_ALERT")
    severity: str = Field(..., pattern="^(HIGH|MEDIUM|LOW)$")
    drug_pair: list[str] | None = Field(default=None, max_length=2)
    interaction_description: str | None = None
    source: str = Field(default="RXNAV", pattern="^(RXNAV|OPENFDA|SYSTEM)$")
    interaction_check_status: str = Field(
        default="COMPLETE", pattern="^(COMPLETE|INCOMPLETE)$"
    )
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata")

    model_config = {"populate_by_name": True}


class PharmacistAlertRead(PharmacistAlertCreate):
    """Response body for a created alert."""

    id: uuid.UUID
    encounter_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
```

### 3. Implement `backend/app/routers/encounters/alerts.py`

```python
"""FastAPI router — POST /api/v1/encounters/{encounter_id}/alerts.

Design refs:
    US-031 AC Scenario 1 — HTTP 201, IMMEDIATE Pub/Sub for HIGH severity
    US-031 AC Scenario 4 — INCOMPLETE status persisted
    design.md §3.3        — /api/v1/encounters router; RBAC PHARMACIST|ADMIN
    ADR-001               — Pub/Sub publish before response
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_roles
from app.core.pubsub import get_pubsub_client
from app.db.session import get_db_write
from app.models.pharmacist_alert import PharmacistAlert
from app.schemas.pharmacist_alert import PharmacistAlertCreate, PharmacistAlertRead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/encounters", tags=["alerts"])

_NOTIFICATION_TOPIC = "notification-requests"


@router.post(
    "/{encounter_id}/alerts",
    response_model=PharmacistAlertRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pharmacist interaction alert for an encounter",
)
async def create_pharmacist_alert(
    encounter_id: uuid.UUID,
    payload: PharmacistAlertCreate,
    db: AsyncSession = Depends(get_db_write),
    pubsub=Depends(get_pubsub_client),
    _claims=Depends(require_roles(["PHARMACIST", "ADMIN"])),
) -> PharmacistAlertRead:
    """Persist a pharmacist alert and publish a Pub/Sub notification.

    - ``HIGH`` severity → ``priority=IMMEDIATE`` on ``notification-requests``
    - ``INCOMPLETE`` status → stored on the alert record for dashboard display

    Args:
        encounter_id: UUID of the encounter record.
        payload: Alert creation payload.
        db: Async write session (Cloud SQL primary).
        pubsub: GCP Pub/Sub async publisher.
        _claims: Validated JWT claims with PHARMACIST or ADMIN role.

    Returns:
        Newly created ``PharmacistAlertRead`` schema.

    Raises:
        HTTPException 422: If severity or source fields fail validation.
    """
    alert = PharmacistAlert(
        encounter_id=encounter_id,
        alert_type=payload.alert_type,
        severity=payload.severity,
        drug_pair=payload.drug_pair,
        interaction_description=payload.interaction_description,
        source=payload.source,
        interaction_check_status=payload.interaction_check_status,
        metadata_=payload.metadata_,
    )
    db.add(alert)
    await db.flush()  # Assign PK before publishing

    # Publish notification
    notification_priority = "IMMEDIATE" if payload.severity == "HIGH" else "STANDARD"
    message = json.dumps(
        {
            "event_type": "PHARMACIST_ALERT",
            "alert_id": str(alert.id),
            "encounter_id": str(encounter_id),
            "severity": payload.severity,
            "priority": notification_priority,
            "drug_pair": payload.drug_pair,
            "interaction_check_status": payload.interaction_check_status,
        }
    ).encode()

    await pubsub.publish(topic=_NOTIFICATION_TOPIC, data=message)
    logger.info(
        "Published PHARMACIST_ALERT alert_id=%s encounter_id=%s priority=%s",
        alert.id,
        encounter_id,
        notification_priority,
    )

    await db.commit()
    await db.refresh(alert)

    return PharmacistAlertRead.model_validate(alert)
```

### 4. Register router in `backend/app/main.py`

```python
from app.routers.encounters.alerts import router as alerts_router
app.include_router(alerts_router)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/models/pharmacist_alert.py` | Create |
| `backend/app/schemas/pharmacist_alert.py` | Create |
| `backend/app/routers/encounters/alerts.py` | Create |
| `backend/app/main.py` | Update — register `alerts_router` |

---

## Validation

- [ ] `POST /api/v1/encounters/{id}/alerts` returns HTTP 201 with created alert body
- [ ] `severity=HIGH` → Pub/Sub message `priority=IMMEDIATE`
- [ ] `severity=MEDIUM` → Pub/Sub message `priority=STANDARD`
- [ ] `interaction_check_status=INCOMPLETE` persisted correctly
- [ ] Non-PHARMACIST/ADMIN role → HTTP 403
- [ ] Alert ID assigned before Pub/Sub publish (flush before publish)

---

## Definition of Done

- [ ] ORM model, schemas, and router implemented and peer-reviewed
- [ ] Alembic migration generated for `pharmacist_alerts` table
- [ ] Unit tests in TASK-008 assert Pub/Sub call with correct priority
- [ ] RBAC guard verified with mocked JWT claims
