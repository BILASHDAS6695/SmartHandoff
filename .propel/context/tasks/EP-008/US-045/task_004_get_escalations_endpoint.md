---
id: TASK-004
title: "GET /api/v1/chat/escalations — Patient-Scoped & Staff Query Endpoint"
user_story: US-045
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-045/TASK-001, US-045/TASK-002, US-045/TASK-003]
---

# TASK-004: GET /api/v1/chat/escalations — Patient-Scoped & Staff Query Endpoint

> **Story:** US-045 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements `GET /api/v1/chat/escalations` — the endpoint that returns escalation records. Two access modes exist:

| Caller | JWT Role | Scope | Query Param |
|--------|----------|-------|-------------|
| Patient | `patient` | Own encounter only (enforced by JWT `encounter_id` claim) | `?encounter_id=` must match JWT claim |
| Staff (nurse, physician, admin) | staff roles | Any encounter | `?encounter_id=` optional filter |

### Endpoint behaviour

```
GET /api/v1/chat/escalations?encounter_id={uuid}
Authorization: Bearer {jwt}   ← patient or staff

1. Validate JWT (existing middleware)
2. Determine caller role from token_claims
3. If patient role:
     a. Extract encounter_id claim from JWT
     b. If ?encounter_id query param provided but doesn't match claim → 403
     c. Force filter: WHERE encounter_id = jwt.encounter_id
4. If staff role:
     a. Apply ?encounter_id filter if provided; otherwise return all (paginated)
5. Execute SELECT with ORDER BY notified_at DESC
6. Map to List[EscalationRead] — acknowledgement_time_minutes computed per row
7. Return paginated response
```

### Response fields (US-045 AC Scenario 3)

```json
[
  {
    "id": "...",
    "encounter_id": "...",
    "transcript_message_id": "...",      ← AC Scenario 3 required field
    "notified_user_id": "...",           ← AC Scenario 3 required field
    "notified_at": "...",
    "acknowledged_at": "...",            ← AC Scenario 3 required field
    "acknowledgement_time_minutes": 1.5, ← AC Scenario 3 required field
    "channel": "SMS",
    "urgency_message": "...",            ← AC Scenario 3 required field
    "created_at": "..."
  }
]
```

**Design references:**
- design.md §3.3 — API middleware stack; JWT role claims extracted before handler
- design.md §6.1 ADR-006 — CQRS: GET queries go to FastAPI read API → PostgreSQL read replica
- design.md §8.2 — patient JWT: `encounter_id` claim; 60-minute expiry; encounter-scoped
- design.md §8.3 — RBAC matrix: patient can access own encounter only; staff roles can read more broadly
- design.md §10.1 — HIPAA audit log: PHI access must be logged; `encounter_id` + query params recorded
- US-045 AC Scenario 3 — GET response must include `transcript_message_id`, `urgency_message`, `notified_user_id`, `acknowledged_at`, `acknowledgement_time_minutes`
- US-045 AC Scenario 4 — patient cannot view other patients' escalations (JWT scope enforced server-side)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 3 | All required fields present in `EscalationRead` response |
| Scenario 4 | Patient JWT `encounter_id` claim enforced; other patients' escalations inaccessible |

---

## Implementation Steps

### 1. Extend `api-gateway/app/routers/escalation.py` — add GET endpoint

```python
# Add to the existing escalation router (api-gateway/app/routers/escalation.py)
# Below the existing PATCH /acknowledge route

from typing import Annotated

from fastapi import Query

from backend.app.core.auth import get_current_token_claims  # returns claims dict for any valid JWT


_PATIENT_ROLE = "patient"
_STAFF_ROLES = {"nurse", "physician", "admin", "pharmacist", "bed_manager"}

# Pagination defaults
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


@router.get(
    "/escalations",
    response_model=list[EscalationRead],
    status_code=status.HTTP_200_OK,
    summary="List care team escalations (patient-scoped or staff)",
)
async def get_escalations(
    encounter_id: Annotated[
        str | None,
        Query(description="Filter by encounter UUID"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_PAGE_SIZE),
    ] = _DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
    token_claims: dict = Depends(get_current_token_claims),
    session: AsyncSession = Depends(get_async_session),
) -> list[EscalationRead]:
    """Return escalation records scoped to caller's role.

    Patient role:
        - Returns escalations for own encounter_id (from JWT claim) only.
        - If ?encounter_id provided and does not match JWT claim → 403.
        - Patient cannot discover other encounters' escalation IDs.

    Staff role:
        - Returns escalations filtered by ?encounter_id if provided.
        - Returns all escalations (paginated) if no filter provided.

    Results ordered by notified_at DESC (most recent first).
    """
    caller_role: str = token_claims.get("role", "")

    if caller_role == _PATIENT_ROLE:
        jwt_encounter_id: str | None = token_claims.get("encounter_id")
        if not jwt_encounter_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )
        # If patient supplied ?encounter_id and it doesn't match their JWT → 403
        if encounter_id is not None and encounter_id != jwt_encounter_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )
        # Force scope to patient's own encounter regardless of query param
        filter_encounter_id = jwt_encounter_id

    elif caller_role in _STAFF_ROLES:
        filter_encounter_id = encounter_id  # optional filter; None = all encounters

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    # Build query with optional encounter filter
    query = sa.select(ChatbotEscalation).order_by(
        ChatbotEscalation.notified_at.desc()
    )
    if filter_encounter_id is not None:
        try:
            filter_uuid = _uuid_module.UUID(filter_encounter_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="encounter_id must be a valid UUID.",
            )
        query = query.where(ChatbotEscalation.encounter_id == filter_uuid)

    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.scalars().all()

    # HIPAA audit log — PHI access recorded (no urgency_message content)
    await write_audit_event(
        event_type="ESCALATION_QUERIED",
        encounter_id=filter_encounter_id or "ALL",
        extra={
            "caller_role": caller_role,
            "result_count": len(rows),
            "limit": limit,
            "offset": offset,
        },
    )

    return [EscalationRead.model_validate(row) for row in rows]
```

---

## Validation Checklist

- [ ] `GET /api/v1/chat/escalations?encounter_id={own_id}` with patient JWT → HTTP 200, own escalations only
- [ ] `GET /api/v1/chat/escalations?encounter_id={other_id}` with patient JWT → HTTP 403 `{"detail": "Access denied."}`
- [ ] `GET /api/v1/chat/escalations` (no param) with patient JWT → HTTP 200, own escalations (JWT-scoped)
- [ ] `GET /api/v1/chat/escalations` with staff JWT → HTTP 200, all escalations (paginated)
- [ ] `GET /api/v1/chat/escalations?encounter_id={id}` with staff JWT → HTTP 200, filtered escalations
- [ ] Response includes all AC Scenario 3 fields: `transcript_message_id`, `urgency_message`, `notified_user_id`, `acknowledged_at`, `acknowledgement_time_minutes`
- [ ] `acknowledgement_time_minutes` is `null` for unacknowledged escalations
- [ ] `acknowledgement_time_minutes` is correct float for acknowledged escalations
- [ ] Results ordered by `notified_at DESC`
- [ ] Pagination: `?limit=5&offset=0` returns max 5 rows
- [ ] `?encounter_id=not-a-uuid` → HTTP 422
- [ ] HIPAA audit event written with `caller_role` + `result_count`; no `urgency_message` content

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-045/TASK-001 | Task | `ChatbotEscalation` ORM model + `EscalationRead` schema |
| US-045/TASK-002 | Task | Router file and shared imports |
| US-045/TASK-003 | Task | Shared `_enforce_encounter_scope` pattern and imports |
| `backend/app/core/auth.py` | Module | `get_current_token_claims` — returns claims for patient or staff JWT |
| Cloud SQL read replica | Infra | GET queries routed to read replica (design.md ADR-006) |
