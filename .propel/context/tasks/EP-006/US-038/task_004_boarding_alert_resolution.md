---
id: TASK-004
title: "Boarding Alert Resolution — Set boarding_alert_resolved_at on Bed Assignment"
user_story: US-038
epic: EP-006
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-038/TASK-001, US-035/TASK-005]
---

# TASK-004: Boarding Alert Resolution — Set boarding_alert_resolved_at on Bed Assignment

> **Story:** US-038 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-038 AC Scenario 3 requires that when a bed manager assigns a patient to a bed (via `PATCH /api/v1/beds/{id}/status` marking the bed as `RESERVED`), the active boarding alert for that patient's encounter is resolved by setting `boarding_alert_resolved_at` on the `encounter` row.

This stops subsequent `BoardingMonitor` cycles from re-detecting this encounter as a boarding candidate, because the monitor query includes `WHERE boarding_alert_resolved_at IS NULL` (TASK-002).

The `PATCH /api/v1/beds/{id}/status` endpoint is implemented in US-035 (TASK-005). This task extends that endpoint's handler by adding a call to a new `resolve_boarding_alert()` helper when the new status is `RESERVED`.

Resolution is **conditional** — if no boarding alert was ever sent (`boarding_alert_sent_at IS NULL`), there is nothing to resolve and the helper is a no-op. This preserves correctness for AC Scenario 2 (patient placed before threshold; alert never fired).

**Design references:**
- US-038 AC Scenario 3 — bed assignment via `PATCH /api/v1/beds/{id}/status` (RESERVED) → `boarding_alert_resolved_at` set; no further alerts for that ED stay
- US-038 DoD — "Alert resolution on bed assignment event (set `boarding_alert_resolved_at`)"
- US-035 TASK-005 — `PATCH /api/v1/beds/{id}/status` endpoint implementation
- design.md §8.3 (RBAC) — endpoint restricted to `BedManager` and `Admin` roles (already enforced by US-035)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 2 | `resolve_boarding_alert()` no-op when `boarding_alert_sent_at IS NULL` (patient placed before threshold) |
| Scenario 3 | `boarding_alert_resolved_at` set when `RESERVED` status applied; no further alerts for that encounter |

---

## Implementation Steps

### 1. Create `backend/app/agents/bed_management/boarding_resolver.py`

```python
"""BoardingAlertResolver — resolves active boarding alerts on bed assignment.

Called by ``PATCH /api/v1/beds/{id}/status`` when the new status is RESERVED.
Sets ``boarding_alert_resolved_at`` on the encounter if a boarding alert was
previously sent, stopping future BoardingMonitor cycles from re-detecting it.

No-op if no alert was sent (boarding_alert_sent_at IS NULL) — preserves
correctness for encounters placed before the 2-hour threshold.

Design refs:
    US-038 AC Scenario 2 — no-op when no alert sent (patient placed early)
    US-038 AC Scenario 3 — boarding_alert_resolved_at set on RESERVED assignment
    US-038 DoD           — "Alert resolution on bed assignment event"
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter

logger = logging.getLogger(__name__)


async def resolve_boarding_alert(
    encounter_id: str,
    session: AsyncSession,
) -> bool:
    """Resolve the boarding alert for a given encounter if one was sent.

    Executes an UPDATE ... WHERE boarding_alert_sent_at IS NOT NULL AND
    boarding_alert_resolved_at IS NULL — idempotent and concurrent-safe.

    Args:
        encounter_id: UUID of the encounter whose patient received a bed.
        session: AsyncSession scoped to the primary (write) DB.

    Returns:
        ``True`` if the boarding alert was resolved (row updated).
        ``False`` if no alert was active (no-op path).
    """
    now_utc = datetime.now(UTC)
    result = await session.execute(
        update(Encounter)
        .where(
            Encounter.id == encounter_id,
            Encounter.boarding_alert_sent_at.is_not(None),   # alert was sent
            Encounter.boarding_alert_resolved_at.is_(None),  # not yet resolved
        )
        .values(boarding_alert_resolved_at=now_utc)
        .returning(Encounter.id)
    )

    resolved = result.rowcount > 0
    if resolved:
        logger.info(
            "Boarding alert resolved for encounter %s at %s.",
            encounter_id,
            now_utc.isoformat(),
        )
    else:
        logger.debug(
            "resolve_boarding_alert no-op for encounter %s "
            "(no active boarding alert or already resolved).",
            encounter_id,
        )
    return resolved
```

### 2. Extend `PATCH /api/v1/beds/{id}/status` handler in `api-gateway/app/routers/beds.py`

Locate the existing `patch_bed_status` handler (implemented in US-035/TASK-005) and add the resolver call inside the `if new_status == BedStatus.RESERVED` branch:

```python
# api-gateway/app/routers/beds.py
# ... existing imports ...
from app.agents.bed_management.boarding_resolver import resolve_boarding_alert


@router.patch(
    "/{bed_id}/status",
    response_model=BedStatusResponse,
    summary="Update bed status (BedManager / Admin only)",
)
async def patch_bed_status(
    bed_id: UUID,
    body: BedStatusUpdateRequest,
    session: AsyncSession = Depends(get_write_session),
    current_user: User = Depends(require_role(["BedManager", "Admin"])),
) -> BedStatusResponse:
    """Update bed status and resolve boarding alert if bed is RESERVED."""
    # --- existing bed status update logic (US-035) ---
    bed = await _get_bed_or_404(bed_id, session)
    old_status = bed.status
    bed.status = body.new_status
    bed.status_updated_at = datetime.now(UTC)
    if body.new_status == BedStatus.RESERVED and body.encounter_id:
        bed.reserved_for_encounter_id = body.encounter_id

    # --- US-038: resolve boarding alert when bed assigned ---
    if body.new_status == BedStatus.RESERVED and body.encounter_id:
        await resolve_boarding_alert(
            encounter_id=str(body.encounter_id),
            session=session,
        )

    await session.commit()
    await session.refresh(bed)

    await emit_audit_event(
        user_id=str(current_user.id),
        action="PATCH_BED_STATUS",
        resource_type="bed",
        resource_id=str(bed_id),
        metadata={
            "previous_status": old_status,
            "new_status": body.new_status,
            "encounter_id": str(body.encounter_id) if body.encounter_id else None,
        },
        session=session,
    )
    return BedStatusResponse.model_validate(bed)
```

> **Note:** `resolve_boarding_alert()` is called within the same DB session and before `session.commit()`. This ensures the boarding resolution and the bed status change are committed atomically — if either fails, both roll back.

### 3. Ensure `BedStatusUpdateRequest` carries `encounter_id`

Verify the Pydantic request schema (US-035) includes:

```python
class BedStatusUpdateRequest(BaseModel):
    new_status: BedStatus
    reason: str | None = None
    encounter_id: UUID | None = None  # Required for RESERVED assignments (US-035, US-038)
```

If `encounter_id` is not yet in the schema, add it.

---

## Validation Checklist

- [ ] `resolve_boarding_alert()` returns `False` (no-op) when `boarding_alert_sent_at IS NULL`
- [ ] `resolve_boarding_alert()` returns `True` and sets `boarding_alert_resolved_at` when alert was active
- [ ] `resolve_boarding_alert()` is idempotent — calling twice leaves `boarding_alert_resolved_at` at the first value
- [ ] Boarding resolution and bed status update committed in the same transaction
- [ ] `PATCH /api/v1/beds/{id}/status` endpoint: non-`RESERVED` status changes do NOT call `resolve_boarding_alert()`
- [ ] `PATCH /api/v1/beds/{id}/status` endpoint: missing `encounter_id` on `RESERVED` skips resolution (no crash)
- [ ] After resolution, `BoardingMonitor` query excludes this encounter (confirmed via TASK-002 `WHERE` clause)

---

## Files Changed

| File | Action |
|---|---|
| `backend/app/agents/bed_management/boarding_resolver.py` | Create |
| `api-gateway/app/routers/beds.py` | Modify — add `resolve_boarding_alert()` call in RESERVED branch |
| `api-gateway/app/schemas/beds.py` | Modify — add `encounter_id: UUID | None` to `BedStatusUpdateRequest` if not present |
