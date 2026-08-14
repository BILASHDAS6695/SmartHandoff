"""BoardingAlertResolver — resolves active boarding alerts on bed assignment.

Called by ``PATCH /api/v1/beds/{id}/status`` when the new status is RESERVED.
Sets ``boarding_alert_resolved_at`` on the encounter if a boarding alert was
previously sent, stopping future BoardingMonitor cycles from re-detecting it.

No-op if no alert was sent (boarding_alert_sent_at IS NULL) — preserves
correctness for encounters placed before the 2-hour threshold.

Design refs:
    US-038 AC Scenario 2 — no-op when no alert sent (patient placed early)
    US-038 AC Scenario 3 — boarding_alert_resolved_at set on RESERVED assignment
    US-038 TASK-004      — resolve_boarding_alert() implementation
    US-038 DoD           — "Alert resolution on bed assignment event"
"""
from __future__ import annotations

import logging
import uuid
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

    Design refs:
        US-038 AC Scenario 2 — returns False when no alert sent
        US-038 AC Scenario 3 — sets boarding_alert_resolved_at
        US-038 TASK-004      — idempotent resolution logic
    """
    # Parse encounter_id string to UUID
    try:
        encounter_uuid = uuid.UUID(encounter_id)
    except ValueError:
        logger.error(
            "Invalid encounter_id format: %s — skipping resolution.",
            encounter_id,
        )
        return False

    now_utc = datetime.now(UTC)
    result = await session.execute(
        update(Encounter)
        .where(
            Encounter.id == encounter_uuid,
            Encounter.boarding_alert_sent_at.is_not(None),   # alert was sent
            Encounter.boarding_alert_resolved_at.is_(None),  # not yet resolved
        )
        .values(boarding_alert_resolved_at=now_utc)
        .returning(Encounter.id)
    )

    resolved_row = result.scalar_one_or_none()
    resolved = resolved_row is not None
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
