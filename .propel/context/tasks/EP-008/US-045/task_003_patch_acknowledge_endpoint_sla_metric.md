---
id: TASK-003
title: "PATCH /api/v1/chat/escalation/{id}/acknowledge — Staff-Only Acknowledgement & 2-Minute SLA Metric"
user_story: US-045
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-045/TASK-001, US-045/TASK-002]
---

# TASK-003: PATCH /api/v1/chat/escalation/{id}/acknowledge — Staff-Only Acknowledgement & 2-Minute SLA Metric

> **Story:** US-045 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the staff-only `PATCH /api/v1/chat/escalation/{id}/acknowledge` endpoint. It sets `acknowledged_at` on the `ChatbotEscalation` row and, if acknowledgement took longer than 2 minutes, emits a Cloud Monitoring custom metric to flag the encounter for response-time review.

### Endpoint behaviour

```
PATCH /api/v1/chat/escalation/{id}/acknowledge
Authorization: Bearer {staff_jwt}   ← nurse, physician, or admin role required
Body: EscalationAcknowledge (empty — placeholder for future extension)

1. Validate JWT (existing middleware — design.md §3.3)
2. Verify caller has staff role (nurse | physician | admin) → 403 if not
3. Fetch ChatbotEscalation by id → 404 if not found
4. If acknowledged_at already set → return 200 (idempotent)
5. Set acknowledged_at = now() UTC
6. Commit DB write
7. Compute acknowledgement_time_minutes = (acknowledged_at - notified_at).total_seconds() / 60
8. If acknowledgement_time_minutes > 2.0 → emit Cloud Monitoring metric 'escalation_sla_breach' with encounter_id label
9. Write HIPAA audit event: {encounter_id, escalation_id, event='ESCALATION_ACKNOWLEDGED', ack_time_minutes}
10. Return updated EscalationRead
```

### SLA monitoring (Phase 1: metric-only)

US-045 DoD specifies: *"if >2 min, flag for review (log metric only in Phase 1)"*. This implementation:
- Emits a Cloud Monitoring custom counter metric `escalation_sla_breach` with labels `encounter_id` and `ack_time_bucket` (`0-2min`, `2-5min`, `5+min`)
- Does NOT trigger further automated escalation (EP-007 US-042 handles that)
- Records `acknowledgement_time_minutes` in the HIPAA audit log for compliance reporting

**Design references:**
- design.md §3.3 — middleware stack: JWT Validator → RBAC Enforcer → Handler
- design.md §8.3 — RBAC matrix: nurse, physician, admin can read patient detail; admin manages users; nurse and physician can approve — staff roles verified here
- design.md §10.1 — Cloud Monitoring custom metrics; HIPAA audit log fields; `acknowledgement_time_minutes` added to audit event for SLA tracking
- design.md §10.2 — error handling: DB write failure → 503 + PagerDuty P1 alert (handled by existing DB error middleware)
- US-045 AC Scenario 2 — if acknowledgement > 2 min, encounter flagged for response time review
- US-045 DoD — `PATCH /api/v1/chat/escalation/{id}/acknowledge` staff-only RBAC; acknowledgement time monitored

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `acknowledged_at` timestamp written; `acknowledgement_time_minutes` computed; SLA breach metric emitted if >2 min |
| Scenario 3 | `acknowledged_at` populated on `ChatbotEscalation` row; readable via GET (TASK-004) |
| Scenario 4 | Staff RBAC enforced — patient JWT cannot call this endpoint (403) |

---

## Implementation Steps

### 1. Create monitoring helper

```bash
touch backend/app/agents/patient_comm/escalation/monitoring.py
```

### 2. Implement `backend/app/agents/patient_comm/escalation/monitoring.py`

```python
"""Cloud Monitoring metric emission for escalation SLA tracking (US-045).

Design ref:
    design.md §10.1 — Cloud Monitoring custom metrics
    US-045 AC Scenario 2 / DoD — if >2 min, flag for review (log metric only in Phase 1)
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Metric name registered in Cloud Monitoring
_METRIC_ESCALATION_SLA_BREACH = "escalation_sla_breach"
_METRIC_ESCALATION_ACKNOWLEDGED = "escalation_acknowledged"

# SLA threshold in minutes (US-045 FR-062)
SLA_THRESHOLD_MINUTES: float = 2.0


def _ack_time_bucket(minutes: float) -> str:
    """Categorise acknowledgement time into a label bucket for Cloud Monitoring."""
    if minutes <= 2.0:
        return "0-2min"
    if minutes <= 5.0:
        return "2-5min"
    return "5+min"


def emit_acknowledgement_metric(
    encounter_id: str,
    escalation_id: str,
    ack_time_minutes: float,
) -> None:
    """Emit Cloud Monitoring metric for escalation acknowledgement.

    Emits:
        - 'escalation_acknowledged' always (for SLA distribution dashboard)
        - 'escalation_sla_breach' if ack_time_minutes > SLA_THRESHOLD_MINUTES

    Phase 1: Implemented via structured log entry that Cloud Monitoring
    log-based metrics can pick up. A dedicated Cloud Monitoring metric
    descriptor is provisioned by Terraform (infra/modules/monitoring/).
    """
    bucket = _ack_time_bucket(ack_time_minutes)

    log.info(
        _METRIC_ESCALATION_ACKNOWLEDGED,
        extra={
            "metric": _METRIC_ESCALATION_ACKNOWLEDGED,
            "encounter_id": encounter_id,
            "escalation_id": escalation_id,
            "ack_time_minutes": ack_time_minutes,
            "ack_time_bucket": bucket,
        },
    )

    if ack_time_minutes > SLA_THRESHOLD_MINUTES:
        log.warning(
            _METRIC_ESCALATION_SLA_BREACH,
            extra={
                "metric": _METRIC_ESCALATION_SLA_BREACH,
                "encounter_id": encounter_id,
                "escalation_id": escalation_id,
                "ack_time_minutes": ack_time_minutes,
                "ack_time_bucket": bucket,
            },
        )
```

### 3. Extend `api-gateway/app/routers/escalation.py` — add PATCH endpoint

```python
# Add to the existing escalation router (api-gateway/app/routers/escalation.py)
# Below the existing POST /escalate route

import uuid as _uuid_module

from backend.app.agents.patient_comm.escalation.models import ChatbotEscalation
from backend.app.agents.patient_comm.escalation.monitoring import (
    SLA_THRESHOLD_MINUTES,
    emit_acknowledgement_metric,
)
from backend.app.agents.patient_comm.escalation.schemas import EscalationAcknowledge
from backend.app.core.auth import get_current_staff_token  # raises 403 if not staff role


@router.patch(
    "/escalation/{escalation_id}/acknowledge",
    response_model=EscalationRead,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge a care team escalation (staff-only)",
)
async def patch_acknowledge(
    escalation_id: str,
    body: EscalationAcknowledge,
    token_claims: dict = Depends(get_current_staff_token),  # nurse | physician | admin
    session: AsyncSession = Depends(get_async_session),
) -> EscalationRead:
    """Set acknowledged_at on a ChatbotEscalation and emit SLA metrics.

    Idempotent: if acknowledged_at is already set, returns 200 without
    updating the timestamp (first acknowledgement wins).

    RBAC: staff roles only (nurse, physician, admin).
    Patient JWT → HTTP 403 (get_current_staff_token dependency raises it).
    """
    # Validate escalation_id is a UUID to prevent injection
    try:
        escalation_uuid = _uuid_module.UUID(escalation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="escalation_id must be a valid UUID.",
        )

    result = await session.execute(
        sa.select(ChatbotEscalation).where(
            ChatbotEscalation.id == escalation_uuid
        )
    )
    escalation = result.scalar_one_or_none()

    if escalation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escalation not found.",
        )

    # Idempotent: return existing record if already acknowledged
    if escalation.acknowledged_at is not None:
        log.info(
            "escalation_already_acknowledged",
            extra={"escalation_id": escalation_id},
        )
        return EscalationRead.model_validate(escalation)

    # Set acknowledgement timestamp
    now = datetime.now(timezone.utc)
    escalation.acknowledged_at = now
    await session.commit()

    # Compute SLA and emit metric
    ack_time_minutes = (now - escalation.notified_at).total_seconds() / 60
    emit_acknowledgement_metric(
        encounter_id=str(escalation.encounter_id),
        escalation_id=escalation_id,
        ack_time_minutes=ack_time_minutes,
    )

    # HIPAA audit log (no PHI; ack_time_minutes recorded for compliance)
    await write_audit_event(
        event_type="ESCALATION_ACKNOWLEDGED",
        encounter_id=str(escalation.encounter_id),
        extra={
            "escalation_id": escalation_id,
            "ack_time_minutes": round(ack_time_minutes, 2),
            "sla_breached": ack_time_minutes > SLA_THRESHOLD_MINUTES,
        },
    )

    log.info(
        "escalation_acknowledged",
        extra={
            "escalation_id": escalation_id,
            "encounter_id": str(escalation.encounter_id),
            "ack_time_minutes": round(ack_time_minutes, 2),
        },
    )

    return EscalationRead.model_validate(escalation)
```

---

## Validation Checklist

- [ ] `PATCH /api/v1/chat/escalation/{id}/acknowledge` with valid staff JWT → HTTP 200 + `EscalationRead`
- [ ] `PATCH /api/v1/chat/escalation/{id}/acknowledge` with patient JWT → HTTP 403
- [ ] Second PATCH call (already acknowledged) → HTTP 200 + same `acknowledged_at` (idempotent)
- [ ] `PATCH /api/v1/chat/escalation/not-a-uuid/acknowledge` → HTTP 422
- [ ] `PATCH /api/v1/chat/escalation/{unknown-id}/acknowledge` → HTTP 404
- [ ] `acknowledged_at` is written to DB in UTC timezone
- [ ] `acknowledgement_time_minutes` is calculated correctly (float, 2 decimal places)
- [ ] `escalation_sla_breach` log entry emitted when `ack_time_minutes > 2.0`
- [ ] `escalation_sla_breach` log entry NOT emitted when `ack_time_minutes <= 2.0`
- [ ] `escalation_acknowledged` log entry always emitted
- [ ] HIPAA audit event written with `ack_time_minutes` and `sla_breached` flag; no PHI content

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-045/TASK-001 | Task | `ChatbotEscalation` ORM model and `EscalationRead` schema |
| US-045/TASK-002 | Task | Router file to extend with PATCH route |
| `backend/app/core/auth.py` | Module | `get_current_staff_token` dependency (raises 403 for non-staff) |
| `backend/app/core/audit.py` | Module | `write_audit_event` utility |
| infra/modules/monitoring/ | Terraform | Log-based metric descriptor for `escalation_sla_breach` |
