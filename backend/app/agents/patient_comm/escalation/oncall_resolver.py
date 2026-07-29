"""Resolves the on-call nurse for a given encounter unit (US-045).

Design ref:
    US-045 Technical Notes — notified_user_id resolved from app_user table
    design.md §8.3 — nurse role scope
"""
from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def resolve_oncall_nurse(
    session: AsyncSession,
    unit_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the app_user.id of the on-call nurse for `unit_id`.

    Resolution order:
        1. Nurse with on_call=True assigned to the specific unit
        2. Any nurse with on_call=True (hospital-wide fallback)
        3. None — caller must handle missing nurse scenario

    Returns:
        UUID of on-call nurse, or None if no on-call nurse is available.
    """
    # Attempt 1: unit-specific on-call nurse
    result = await session.execute(
        sa.text(
            """
            SELECT id FROM app_user
            WHERE role = 'nurse'
              AND unit_id = :unit_id
              AND on_call = TRUE
            LIMIT 1
            """
        ),
        {"unit_id": str(unit_id)},
    )
    row = result.fetchone()
    if row:
        return uuid.UUID(str(row[0]))

    # Attempt 2: any hospital-wide on-call nurse
    result = await session.execute(
        sa.text(
            """
            SELECT id FROM app_user
            WHERE role = 'nurse'
              AND on_call = TRUE
            LIMIT 1
            """
        )
    )
    row = result.fetchone()
    if row:
        log.warning(
            "oncall_nurse_unit_fallback",
            extra={"unit_id": str(unit_id)},
        )
        return uuid.UUID(str(row[0]))

    # No on-call nurse available — P1 metric logged by caller
    log.error("oncall_nurse_not_found", extra={"unit_id": str(unit_id)})
    return None
