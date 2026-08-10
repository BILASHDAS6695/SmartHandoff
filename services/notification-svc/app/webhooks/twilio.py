"""Twilio delivery status webhook handler.

Receives `POST /webhooks/twilio/status` from Twilio and updates the
`notification.delivery_status` to DELIVERED (or FAILED for undelivered messages).

Security: Every request is validated against the `X-Twilio-Signature`
header using `twilio.request_validator.RequestValidator` with the
`twilio-auth-token` from Secret Manager (US-064 AC Scenario 3, DoD).
Invalid signatures are rejected with HTTP 403.

Design refs:
    US-064 AC Scenario 3 — webhook updates status=DELIVERED
    US-064 DoD           — X-Twilio-Signature header validation
    OWASP A04            — Insecure design: spoofed webhooks rejected
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from app.core.secrets import get_secret
from app.db.session import get_db_session
from app.models.notification import Notification, NotificationStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])


def _validate_twilio_signature(
    request: Request,
    x_twilio_signature: Annotated[str | None, Header(alias="X-Twilio-Signature")] = None,
) -> None:
    """FastAPI dependency: validate Twilio webhook signature.

    Reconstructs the full callback URL from the request and validates the
    `X-Twilio-Signature` header using the Twilio auth token from Secret Manager.

    Raises:
        HTTPException: 403 Forbidden if signature is invalid or missing.
    """
    if not x_twilio_signature:
        logger.warning("twilio_webhook.missing_signature")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Twilio-Signature header",
        )

    auth_token = get_secret("twilio-auth-token")
    validator = RequestValidator(auth_token)

    # Reconstruct the full callback URL Twilio signed
    url = str(request.url)

    # Form params must be passed as a flat dict for signature validation
    # (accessed synchronously via the form data — resolved before route handler)
    form_params = dict(request.state.form_params) if hasattr(request.state, "form_params") else {}

    is_valid = validator.validate(url, form_params, x_twilio_signature)
    if not is_valid:
        logger.warning(
            "twilio_webhook.invalid_signature",
            extra={"url": url},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio webhook signature",
        )


@router.post(
    "/status",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_validate_twilio_signature)],
    summary="Twilio delivery status callback",
)
async def twilio_status_webhook(
    request: Request,
    MessageSid: Annotated[str, Form()],
    MessageStatus: Annotated[str, Form()],
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Handle Twilio delivery status webhook.

    Updates `notification.delivery_status` based on Twilio's MessageStatus value.
    Correlation performed via `twilio_message_sid` column.

    Twilio MessageStatus values:
        - ``delivered``  → NotificationStatus.DELIVERED
        - ``failed``     → NotificationStatus.FAILED
        - ``undelivered``→ NotificationStatus.FAILED
        - others         → no status change (e.g. ``sent``, ``queued``)

    Args:
        request: FastAPI request (used for signature validation).
        MessageSid: Twilio message SID from form body.
        MessageStatus: Twilio delivery status from form body.
        session: Async DB session.
    """
    # Cache form params on request.state for the signature validator
    form_data = await request.form()
    request.state.form_params = dict(form_data)

    status_map: dict[str, NotificationStatus] = {
        "delivered": NotificationStatus.DELIVERED,
        "failed": NotificationStatus.FAILED,
        "undelivered": NotificationStatus.FAILED,
    }

    new_status = status_map.get(MessageStatus.lower())
    if new_status is None:
        # Intermediate status (sent, queued, etc.) — no action needed
        logger.debug(
            "twilio_webhook.intermediate_status",
            extra={"sid": MessageSid, "twilio_status": MessageStatus},
        )
        return

    from datetime import datetime, timezone
    import sqlalchemy as sa

    now = datetime.now(timezone.utc)
    params = {
        "status": new_status.value,
        "updated_at": now,
        "sid": MessageSid,
    }
    sql = "UPDATE notification SET delivery_status = :status, updated_at = :updated_at"

    if new_status == NotificationStatus.DELIVERED:
        sql += ", delivered_at = :delivered_at"
        params["delivered_at"] = now

    sql += " WHERE twilio_message_sid = :sid"
    
    result = await session.execute(sa.text(sql), params)
    await session.commit()

    if result.rowcount == 0:
        logger.warning(
            "twilio_webhook.sid_not_found",
            extra={"sid": MessageSid, "twilio_status": MessageStatus},
        )
    else:
        logger.info(
            "twilio_webhook.status_updated",
            extra={
                "sid": MessageSid,
                "twilio_status": MessageStatus,
                "new_status": new_status.value,
            },
        )
