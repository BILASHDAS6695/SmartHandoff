"""Notification Service client for sending OTP via SMS (US-064).

This service interfaces with the Notification Service (notification-svc)
to trigger OTP delivery via Twilio Verify API.

Design refs:
    US-052 TASK-002 — triggers OTP delivery
    US-064 — Notification Service implementation
    design.md §3.1 — Notification Service architecture
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from api_gateway.app.core.config import settings

log = logging.getLogger(__name__)

# Notification Service endpoint path for OTP delivery
_NOTIFY_OTP_ENDPOINT = "/internal/notify/otp"


async def send_otp_notification(
    patient_id: str,
    otp: str,
    phone_number: Optional[str] = None,
) -> bool:
    """Send OTP to patient via SMS using Notification Service.

    Calls POST /internal/notify/otp on the Notification Service to trigger
    Twilio Verify OTP delivery.

    Args:
        patient_id: UUID of the patient (for audit trail)
        otp: 6-digit OTP plaintext to send
        phone_number: Optional phone number if not resolved from patient_id

    Returns:
        True if notification was queued successfully; False otherwise

    Raises:
        httpx.RequestError: Network error calling Notification Service
        httpx.TimeoutError: Notification Service timeout

    Security notes:
        - OTP is sent in request body (HTTPS only)
        - Patient ID logged for audit; phone number never logged
        - Failures logged but not re-raised (non-blocking)
    """
    try:
        url = f"{settings.NOTIFICATION_SERVICE_URL}{_NOTIFY_OTP_ENDPOINT}"
        payload = {
            "patient_id": patient_id,
            "otp": otp,
        }
        if phone_number:
            payload["phone_number"] = phone_number

        async with httpx.AsyncClient(
            timeout=settings.NOTIFICATION_SERVICE_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        log.info(
            "otp_notification_sent",
            extra={"patient_id": patient_id},
            # otp and phone_number intentionally omitted from logs (secrets, PHI)
        )
        return True

    except httpx.TimeoutError:
        log.error(
            "otp_notification_timeout",
            extra={"patient_id": patient_id},
        )
        return False
    except httpx.RequestError as e:
        log.error(
            "otp_notification_error",
            extra={"patient_id": patient_id, "error": str(e)},
        )
        return False
    except Exception as e:
        log.error(
            "otp_notification_unexpected_error",
            extra={"patient_id": patient_id, "error": str(e)},
        )
        return False
