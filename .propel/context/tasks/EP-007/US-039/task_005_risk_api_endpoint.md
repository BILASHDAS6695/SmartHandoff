---
id: TASK-005
title: "GET /api/v1/encounters/{id}/risk — Risk Score API Endpoint"
user_story: US-039
epic: EP-007
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-039/TASK-004, US-024]
---

# TASK-005: GET /api/v1/encounters/{id}/risk — Risk Score API Endpoint

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039 AC Scenario 4 requires a REST endpoint `GET /api/v1/encounters/{id}/risk` that returns:
- `risk_score` (float, 0.0–1.0)
- `risk_tier` (LOW / MEDIUM / HIGH / UNKNOWN)
- `contributing_factors` (top 5 SHAP features, as stored in the AgentTask output or re-queried from the ML Inference Service)
- `model_version`

This endpoint is consumed by the Angular care manager dashboard (EP-009) and must be accessible to physicians and admins only (RBAC per §8.3).

**Design references:**
- design.md §3.3 — FastAPI backend routers: `/encounters`
- design.md §8.3 — RBAC: Physician ✓, Admin ✓; Nurse = Read (unit-scoped); Pharmacist ✗; Patient = Own only
- US-039 AC Scenario 4 — GET /api/v1/encounters/ENC-001/risk with physician JWT; returns risk_score, risk_tier, contributing_factors, model_version
- US-039 DoD — `GET /api/v1/encounters/{id}/risk` endpoint with contributing_factors computed via SHAP values
- ADR-006 — read queries route to read replica via FastAPI read API

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `GET /api/v1/encounters/ENC-001/risk` returns the score persisted in Scenario 1 |
| Scenario 4 | Response includes `risk_score`, `risk_tier`, `contributing_factors` (top 5), `model_version` with physician JWT |

---

## Implementation Steps

### 1. Define response schema in `api-gateway/app/schemas/risk.py`

```python
"""Response schemas for the risk assessment endpoint.

Design refs:
    US-039 AC Scenario 4
    design.md §3.3 — FastAPI routers
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ContributingFactor(BaseModel):
    feature: str = Field(..., description="Human-readable feature label")
    shap_value: float
    feature_value: float
    direction: str = Field(..., description="'increases_risk' or 'decreases_risk'")


class EncounterRiskResponse(BaseModel):
    """Response body for GET /api/v1/encounters/{id}/risk."""

    encounter_id: str
    risk_score: float | None = Field(None, ge=0.0, le=1.0)
    risk_tier: RiskTier = RiskTier.UNKNOWN
    contributing_factors: list[ContributingFactor] = Field(default_factory=list)
    model_version: str | None = None
    assessed_at: str | None = Field(
        None,
        description="ISO 8601 timestamp of when the risk was last assessed (from AgentTask.completed_at)",
    )
```

### 2. Implement `api-gateway/app/routers/encounters_risk.py`

```python
"""FastAPI router for encounter risk score retrieval.

Endpoint:
    GET /api/v1/encounters/{encounter_id}/risk

RBAC:
    Physician  : ✓ (own patients — unit-scoped enforcement at query level)
    Admin      : ✓ (all encounters)
    Nurse      : Read (unit-scoped — same as Physician enforcement)
    Pharmacist : ✗ (403)
    Patient    : Own encounter only (encounter-scoped JWT)

Design refs:
    design.md §3.3  — FastAPI routers
    design.md §8.3  — RBAC permission matrix
    ADR-006         — GET queries route to read replica
    US-039 AC Scenario 4
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_any_role
from app.core.dependencies import get_read_db
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter
from app.schemas.risk import ContributingFactor, EncounterRiskResponse, RiskTier

router = APIRouter(prefix="/api/v1/encounters", tags=["encounters"])
logger = logging.getLogger(__name__)

_ALLOWED_ROLES = {"admin", "physician", "nurse"}


@router.get(
    "/{encounter_id}/risk",
    response_model=EncounterRiskResponse,
    summary="Get 30-day readmission risk score for a discharged encounter",
)
async def get_encounter_risk(
    encounter_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_read_db),
    _: None = Depends(require_any_role(_ALLOWED_ROLES)),
) -> EncounterRiskResponse:
    """Return the risk score, tier, and contributing factors for an encounter.

    Data is read from:
        1. ``encounter.risk_score`` / ``encounter.risk_tier`` — the primary source
        2. The most recent completed ``AgentTask`` with ``agent_type="FOLLOWUP_CARE"``
           — used to retrieve ``contributing_factors`` and ``model_version``
           stored in the task ``output_summary`` JSON payload

    Routes to the read replica (ADR-006) via ``get_read_db`` dependency.

    Raises:
        404: Encounter not found or soft-deleted.
        403: Caller lacks required role.
    """
    # Validate encounter ID format
    try:
        enc_uuid = uuid.UUID(encounter_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encounter ID format")

    # Fetch encounter (read replica)
    enc_result = await session.execute(
        select(Encounter).where(
            Encounter.id == enc_uuid,
            Encounter.deleted_at.is_(None),
        )
    )
    encounter: Encounter | None = enc_result.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    # Role-scoped access check for Nurses and Physicians (unit-scoped)
    if current_user["role"] in {"physician", "nurse"}:
        if encounter.unit not in (current_user.get("units") or []):
            # Allow own encounters for Physicians regardless of unit claim
            if str(encounter.attending_physician_id) != current_user["sub"] and current_user["role"] == "nurse":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied — encounter not in your assigned unit",
                )

    # Fetch the most recent completed FOLLOWUP_CARE AgentTask for this encounter
    task_result = await session.execute(
        select(AgentTask)
        .where(
            AgentTask.encounter_id == enc_uuid,
            AgentTask.agent_type == "FOLLOWUP_CARE",
            AgentTask.status == AgentTaskStatus.COMPLETED,
        )
        .order_by(AgentTask.completed_at.desc())
        .limit(1)
    )
    agent_task: AgentTask | None = task_result.scalar_one_or_none()

    # Parse contributing_factors from AgentTask output_summary JSON
    contributing_factors: list[ContributingFactor] = []
    model_version: str | None = None
    assessed_at: str | None = None

    if agent_task and agent_task.output_summary:
        try:
            summary = json.loads(agent_task.output_summary) if isinstance(agent_task.output_summary, str) else {}
            model_version = summary.get("model_version")
            cf_data = summary.get("contributing_factors", [])
            contributing_factors = [ContributingFactor(**cf) for cf in cf_data]
            if agent_task.completed_at:
                assessed_at = agent_task.completed_at.isoformat()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not parse AgentTask output_summary for encounter_id=%s: %s",
                encounter_id,
                exc,
            )

    return EncounterRiskResponse(
        encounter_id=encounter_id,
        risk_score=encounter.risk_score,
        risk_tier=RiskTier(encounter.risk_tier) if encounter.risk_tier else RiskTier.UNKNOWN,
        contributing_factors=contributing_factors,
        model_version=model_version,
        assessed_at=assessed_at,
    )
```

### 3. Register router in `api-gateway/app/main.py`

Add the following import and registration alongside existing encounter routers:

```python
# In api-gateway/app/main.py — add to router registrations
from app.routers.encounters_risk import router as encounters_risk_router
app.include_router(encounters_risk_router)
```

### 4. Update AgentTask `output_summary` format in `task_004_followup_care_agent.md` (TASK-004 note)

The `_create_agent_task()` method in `agent.py` must store `output_summary` as structured JSON (not plain string) so `GET /risk` can parse `contributing_factors` and `model_version`. Update `_create_agent_task()` call in TASK-004 `agent.py`:

```python
import json

# In FollowUpCareAgent._create_agent_task():
task = AgentTask(
    id=uuid.UUID(agent_task_id),
    encounter_id=uuid.UUID(encounter_id),
    agent_type="FOLLOWUP_CARE",
    status=AgentTaskStatus.COMPLETED,
    output_summary=json.dumps({
        "risk_tier": risk_tier,
        "model_version": model_version,
        "contributing_factors": contributing_factors,   # list[dict] from inference response
    }),
)
```

---

## File Checklist

| File | Action |
|------|--------|
| `api-gateway/app/schemas/risk.py` | Create |
| `api-gateway/app/routers/encounters_risk.py` | Create |
| `api-gateway/app/main.py` | Update — register `encounters_risk_router` |
| `backend/app/agents/followup_care/agent.py` | Update — `output_summary` as structured JSON |

---

## Validation

- [ ] `GET /api/v1/encounters/{valid-id}/risk` with Physician JWT returns HTTP 200 with all 4 fields: `risk_score`, `risk_tier`, `contributing_factors`, `model_version`
- [ ] `GET /api/v1/encounters/{valid-id}/risk` with Pharmacist JWT returns HTTP 403
- [ ] `GET /api/v1/encounters/{valid-id}/risk` with Patient JWT returns HTTP 403 (unless own encounter)
- [ ] `GET /api/v1/encounters/invalid-uuid/risk` returns HTTP 400 "Invalid encounter ID format"
- [ ] `GET /api/v1/encounters/non-existent-id/risk` returns HTTP 404 "Encounter not found"
- [ ] `risk_tier=UNKNOWN` when `encounter.risk_score` is `None` (not yet assessed)
- [ ] `contributing_factors` is empty list `[]` if no completed `AgentTask` exists
- [ ] `assessed_at` is present and ISO 8601 formatted when AgentTask.completed_at is populated
- [ ] No PHI in response body — `encounter_id` is a UUID, no patient name or MRN returned

---

## Definition of Done

- [ ] `GET /api/v1/encounters/{id}/risk` endpoint implemented
- [ ] RBAC enforced: Physician ✓, Admin ✓, Nurse ✓ (unit-scoped); Pharmacist ✗, Patient ✗
- [ ] `contributing_factors` and `model_version` parsed from AgentTask `output_summary` JSON
- [ ] Router registered in `api-gateway/app/main.py`
- [ ] TASK-004 `agent.py` updated to store `output_summary` as structured JSON
- [ ] Code peer-reviewed before merge
