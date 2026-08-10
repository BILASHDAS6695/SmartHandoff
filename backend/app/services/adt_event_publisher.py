"""ADT event publisher — records ADT events in DB and broadcasts to SignalR.

Encounters already exist in the SmartHandoff database. This service:
  1. Inserts a row into `adt_event` for every clinically relevant encounter change.
  2. Broadcasts the event via Azure SignalR Service to the relevant unit group.

This makes `adt_event` the audit trail and SignalR the real-time delivery layer.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.adt_event import AdtEvent
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.signalr.broadcaster import SignalRBroadcaster

logger = logging.getLogger(__name__)

# Map encounter.status to HL7 ADT event type.
_STATUS_TO_ADT_EVENT_TYPE: dict[str, str] = {
    "REGISTERED": "A04",
    "PRE_ADMISSION": "A04",
    "ADMITTED": "A01",
    "TRANSFERRED": "A02",
    "DISCHARGED": "A03",
}

# Active statuses that should keep the encounter visible in the dashboard.
_ACTIVE_STATUSES = {"REGISTERED", "PRE_ADMISSION", "ADMITTED", "TRANSFERRED"}


class AdtEventPublisher:
    """Publish ADT events for encounter lifecycle changes."""

    def __init__(self, broadcaster: SignalRBroadcaster | None = None) -> None:
        settings = get_settings()
        conn = settings.AZURE_SIGNALR_CONNECTION_STRING
        self._broadcaster = broadcaster or (SignalRBroadcaster(conn) if conn else None)

    async def publish_for_encounter(
        self,
        db: AsyncSession,
        encounter: Encounter,
        patient: Patient,
        event_timestamp: datetime | None = None,
    ) -> AdtEvent:
        """Create an adt_event row and broadcast it for the given encounter.

        Args:
            db: Write database session.
            encounter: The encounter that changed.
            patient: The patient linked to the encounter (for display name).
            event_timestamp: Optional timestamp; defaults to UTC now.

        Returns:
            The created AdtEvent record.
        """
        event_type = _STATUS_TO_ADT_EVENT_TYPE.get(encounter.status, "A08")
        timestamp = event_timestamp or datetime.now(timezone.utc)
        source_message_id = f"SYNTH-{encounter.id}-{int(timestamp.timestamp())}"

        adt_event = AdtEvent(
            encounter_id=encounter.id,
            source_message_id=source_message_id,
            event_type=event_type,
            event_timestamp=timestamp,
            sending_facility=encounter.unit,
            processing_status="processed",
        )
        db.add(adt_event)
        await db.flush([adt_event])

        payload = self._build_payload(adt_event, encounter, patient)

        if self._broadcaster and encounter.unit:
            try:
                await self._broadcaster.broadcast_adt_event(payload)
                logger.info(
                    "ADT event broadcast",
                    extra={"event_id": str(adt_event.id), "unit": encounter.unit},
                )
            except Exception as exc:
                # Broadcasting must never fail the DB transaction.
                logger.warning(
                    "ADT broadcast failed",
                    extra={"event_id": str(adt_event.id), "error": str(exc)},
                )
        else:
            logger.info(
                "ADT event recorded without broadcast",
                extra={"event_id": str(adt_event.id), "unit": encounter.unit},
            )

        return adt_event

    @staticmethod
    def _build_payload(
        adt_event: AdtEvent,
        encounter: Encounter,
        patient: Patient,
    ) -> dict:
        """Build the SignalR adt_event_received payload."""
        display_name = f"{patient.last_name}, {patient.first_name}".strip(", ")
        if not display_name:
            display_name = f"Patient {patient.id}"

        return {
            "eventType": adt_event.event_type,
            "patientUnit": encounter.unit or "UNKNOWN",
            "timestamp": adt_event.event_timestamp.isoformat(),
            "encounterId": str(encounter.id),
            "patientId": str(patient.id),
            "patientDisplayName": display_name,
            "encounterStatus": encounter.status,
            "riskTier": encounter.risk_tier,
            "isActive": encounter.status in _ACTIVE_STATUSES,
        }
