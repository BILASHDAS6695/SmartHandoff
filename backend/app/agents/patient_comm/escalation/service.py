"""EscalationService — domain logic for creating escalation records (US-045).

Coordinates:
    - on-call nurse resolution (oncall_resolver)
    - ChatbotEscalation DB write
    - Pub/Sub alert publish (fire-and-forget via asyncio.create_task)
    - SignalR push of EscalationConfirmedMessage

Design ref:
    US-045 Technical Notes — fire-and-forget pattern
    design.md §7.5 AIR-040 — EscalationAlertPayload format
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.escalation.models import ChatbotEscalation
from backend.app.agents.patient_comm.escalation.oncall_resolver import resolve_oncall_nurse
from backend.app.agents.patient_comm.escalation.pubsub_publisher import publish_escalation_alert
from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationAlertPayload,
    EscalationConfirmedMessage,
    EscalationCreate,
    EscalationRead,
    NotificationChannel,
)
from backend.app.core.signalr import signalr_hub  # existing SignalR hub client

log = logging.getLogger(__name__)

# P1 Cloud Monitoring metric name for missing on-call nurse
_METRIC_NO_ONCALL_NURSE = "escalation_no_oncall_nurse"


async def create_escalation(
    session: AsyncSession,
    payload: EscalationCreate,
    patient_first_name: str,
    encounter_unit_id: uuid.UUID,
) -> tuple[ChatbotEscalation, EscalationConfirmedMessage]:
    """Create a ChatbotEscalation record and trigger nurse notification.

    Returns:
        Tuple of (ORM row, EscalationConfirmedMessage) for the caller to:
            - return EscalationRead to the HTTP client
            - push EscalationConfirmedMessage to SignalR

    Steps:
        1. Resolve on-call nurse
        2. Write ChatbotEscalation row
        3. Schedule Pub/Sub publish as background task (fire-and-forget)
        4. Build EscalationConfirmedMessage for SignalR push
    """
    notified_at = datetime.now(timezone.utc)
    notified_user_id = await resolve_oncall_nurse(session, encounter_unit_id)

    if notified_user_id is None:
        log.error(_METRIC_NO_ONCALL_NURSE, extra={"encounter_id": payload.encounter_id})

    row = ChatbotEscalation(
        encounter_id=uuid.UUID(payload.encounter_id),
        transcript_message_id=uuid.UUID(payload.transcript_message_id),
        notified_user_id=notified_user_id,
        notified_at=notified_at,
        acknowledged_at=None,
        channel=payload.channel.value,
        urgency_message=payload.urgency_message,
    )
    session.add(row)
    await session.flush()  # populate row.id without committing the outer transaction
    await session.commit()

    # Fire-and-forget Pub/Sub publish
    alert_payload = EscalationAlertPayload(
        escalation_id=str(row.id),
        encounter_id=payload.encounter_id,
        notified_user_id=str(notified_user_id) if notified_user_id else "UNRESOLVED",
        patient_first_name=patient_first_name,
        urgency_message_summary=payload.urgency_message,
        channel=payload.channel,
        timestamp=notified_at,
    )
    asyncio.create_task(publish_escalation_alert(alert_payload))

    confirmed_msg = EscalationConfirmedMessage(
        encounter_id=payload.encounter_id,
        escalation_id=str(row.id),
    )

    return row, confirmed_msg
