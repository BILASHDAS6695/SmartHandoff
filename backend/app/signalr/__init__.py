"""SignalR hub abstraction — broadcasts real-time events to care team dashboard.

This stub provides the interface for sending events to connected dashboard
clients via Azure SignalR Service or a compatible WebSocket hub.

In Sprint 1, the hub is a no-op stub. A full Azure SignalR Service
integration is planned for EP-002 (real-time dashboard).

Design refs:
    NFR-006  — SignalR notification latency ≤1 second
    US-015   — ENCOUNTER_CANCELLED broadcast to care team dashboard
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SignalRHub:
    """Async interface for broadcasting events to SignalR groups.

    In production this wraps Azure SignalR Service REST API calls.
    In Sprint 1 (stub), events are logged for observability only.
    """

    async def send_to_group(
        self,
        *,
        group: str,
        event: str,
        payload: dict,
    ) -> None:
        """Broadcast ``event`` with ``payload`` to all clients in ``group``.

        Args:
            group:   SignalR group name (e.g. ``"encounter-{uuid}"``).
            event:   Event name that clients subscribe to (e.g. ``"ENCOUNTER_CANCELLED"``).
            payload: JSON-serialisable dict sent as the message body.
        """
        # Sprint 1 stub: log the broadcast for observability
        logger.info(
            "signalr_hub.send_to_group",
            extra={
                "group": group,
                "event": event,
                # Only non-PHI fields from payload are logged
                "encounter_id": payload.get("encounter_id"),
                "event_type": payload.get("event_type"),
            },
        )
