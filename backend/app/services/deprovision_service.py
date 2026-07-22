"""User deprovisioning service — shared between manual and SCIM-triggered flows.

Called by:
  - DELETE /api/v1/admin/users/{id}          (US-059 — manual deprovision)
  - DELETE /api/v1/admin/scim/Users/{id}     (US-060 — SCIM deprovision)
  - SCIM PATCH active=False                  (US-060 — PATCH-based deprovision)

Responsibilities:
  1. Look up app_user.current_jti
  2. Add current_jti to the Redis blocklist via add_to_blocklist() (US-059)
  3. Set app_user.deprovisioned_at = UTC now
  4. Write an audit_log entry

Design refs:
    design.md §7.4 AIR-032  — SCIM deprovisioning / JWT revocation
    US-059/TASK-001          — JwtBlocklistService (add_to_blocklist)
    US-059/TASK-004          — deprovision endpoint + DB schema
    SEC-009, SEC-011
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt_blocklist import add_to_blocklist
from app.models.app_user import AppUser

logger = logging.getLogger(__name__)


async def deprovision_user(user_id: uuid.UUID, db: AsyncSession) -> AppUser:
    """Deprovision a user: blocklist JWT + set deprovisioned_at + write audit log.

    This function is idempotent — if the user is already deprovisioned it
    returns immediately without modifying any state.

    Args:
        user_id: The SmartHandoff UUID of the user to deprovision.
        db:      Open async SQLAlchemy write session.

    Returns:
        The updated (or already-deprovisioned) ``AppUser`` instance.

    Raises:
        LookupError: If no user with ``user_id`` exists in the database.

    Note:
        Already-deprovisioned users are handled idempotently — the function
        returns the existing user without modifying state or raising an exception.
    """
    result = await db.execute(select(AppUser).where(AppUser.id == user_id))
    user: AppUser | None = result.scalar_one_or_none()

    if user is None:
        raise LookupError(f"User {user_id} not found")

    # Idempotent — already deprovisioned: no-op
    if user.deprovisioned_at is not None:
        logger.info(
            "deprovision_user: already deprovisioned — idempotent no-op",
            extra={"user_id": str(user_id)},
        )
        return user

    # 1. Blocklist current JWT (current_jti may be None for users who never logged in)
    if user.current_jti:
        # Use 8h max JWT lifetime as safe TTL since we don't store exp separately.
        exp = int(time.time()) + (8 * 3600)
        add_to_blocklist(user.current_jti, exp)
        logger.info(
            "deprovision_user: active JWT blocklisted",
            extra={"user_id": str(user_id), "jti": user.current_jti},
        )

    # 2. Set deprovisioned_at
    user.deprovisioned_at = datetime.now(timezone.utc)

    # 3. Write audit_log entry using the existing AuditLog schema
    from app.models.audit_log import AuditLog
    audit = AuditLog(
        id=uuid.uuid4(),
        user_id=user_id,
        user_role="system",
        resource_type="user",
        resource_id=str(user_id),
        action="delete",
        endpoint="/deprovision",
        outcome="success",
    )
    db.add(audit)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "deprovision_user: complete",
        extra={"event": "user_deprovisioned", "user_id": str(user_id)},
    )
    return user
