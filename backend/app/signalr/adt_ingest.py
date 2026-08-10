"""ADT ingestion from a FHIR R4 server.

Polls the configured FHIR server for recently changed Encounter resources,
detects admission/discharge/transfer (ADT) events, and broadcasts them via
Azure SignalR Service to unit-scoped dashboard groups.

Usage:
    service = AdtIngestService(broadcaster)
    await service.poll_and_broadcast(since=datetime.utcnow() - timedelta(minutes=5))
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import get_settings
from app.signalr.broadcaster import SignalRBroadcaster

logger = logging.getLogger(__name__)

# HL7 ADT event type mapping based on Encounter.status transitions.
_ADT_EVENT_TYPES: dict[str, str] = {
    "planned": "A04",      # Register
    "arrived": "A01",      # Admit
    "triaged": "A01",      # Admit
    "in-progress": "A01",  # Admit
    "onleave": "A02",      # Transfer
    "finished": "A03",     # Discharge
    "cancelled": "A11",    # Cancel Admit
    "entered-in-error": "A08",  # Update
    "unknown": "A08",      # Update
}

# Encounter.status values that represent an active admission.
_ACTIVE_ENCOUNTER_STATUSES = {"arrived", "triaged", "in-progress", "onleave"}


class AdtIngestService:
    """Poll FHIR server for recent Encounter changes and broadcast ADT events."""

    def __init__(self, broadcaster: SignalRBroadcaster) -> None:
        self._broadcaster = broadcaster
        self._settings = get_settings()
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._http_client.aclose()

    async def poll_and_broadcast(
        self,
        since: datetime | None = None,
        unit: str = "ICU",
    ) -> dict[str, Any]:
        """Fetch recent encounters and broadcast an ADT event for each one.

        Args:
            since: Only encounters updated after this time are considered.
                   Defaults to 5 minutes ago.
            unit: Unit identifier assigned to synthetic ADT events.

        Returns:
            Summary dict with broadcast count and errors.
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(minutes=5)

        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        base_url = self._settings.FHIR_BASE_URL.rstrip("/")
        url = f"{base_url}/Encounter"
        params = {
            "_lastUpdated": f"gt{since_str}",
            "_sort": "-_lastUpdated",
            "_count": "100",
        }

        logger.info("Polling FHIR for ADT events", extra={"since": since_str, "unit": unit})

        try:
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("Failed to fetch encounters from FHIR server")
            return {"broadcast_count": 0, "errors": 1, "error_message": str(exc)}

        bundle = response.json()
        entries = bundle.get("entry", [])
        broadcast_count = 0
        errors = 0

        for entry in entries:
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Encounter":
                continue

            try:
                payload = self._encounter_to_adt_payload(resource, unit)
                await self._broadcaster.broadcast_adt_event(payload)
                broadcast_count += 1
            except Exception as exc:
                logger.warning("Failed to broadcast ADT event for encounter", extra={"error": str(exc)})
                errors += 1

        logger.info(
            "ADT polling complete",
            extra={"broadcast_count": broadcast_count, "errors": errors},
        )
        return {"broadcast_count": broadcast_count, "errors": errors}

    def _encounter_to_adt_payload(self, encounter: dict[str, Any], unit: str) -> dict[str, Any]:
        """Map a FHIR Encounter resource to the ADT event payload shape."""
        status = encounter.get("status", "unknown")
        event_type = _ADT_EVENT_TYPES.get(status, "A08")

        patient_ref = encounter.get("subject", {}).get("reference", "")
        patient_id = patient_ref.split("/")[-1] if patient_ref else "unknown"

        # Attempt to extract patient display name from included Patient or reference
        patient_name = self._extract_patient_name(encounter, patient_id)

        period = encounter.get("period", {})
        period_start = period.get("start")
        period_end = period.get("end")

        # Derive encounter ID. Prefer the FHIR id; fall back to Patient id.
        encounter_id = encounter.get("id", patient_id)

        # Determine if this is an active admission for the dashboard.
        is_active = status in _ACTIVE_ENCOUNTER_STATUSES

        return {
            "eventType": event_type,
            "patientUnit": unit,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "encounterId": encounter_id,
            "patientDisplayName": patient_name,
            "patientId": patient_id,
            "encounterStatus": status,
            "periodStart": period_start,
            "periodEnd": period_end,
            "isActive": is_active,
        }

    def _extract_patient_name(self, encounter: dict[str, Any], fallback_id: str) -> str:
        """Try to read patient name from embedded Patient resource."""
        # FHIR _include can embed the Patient in entry.search.included
        included = encounter.get("contained", [])
        for resource in included:
            if resource.get("resourceType") == "Patient" and resource.get("name"):
                name = resource["name"][0]
                family = name.get("family", "")
                given = name.get("given", [""])[0] if name.get("given") else ""
                return f"{family}, {given}".strip(", ")

        # Fallback: Patient reference display
        display = encounter.get("subject", {}).get("display", "")
        if display:
            return display

        return f"Patient {fallback_id}"
