"""Azure SignalR Service REST API broadcaster.

Stateless broadcast client for Cloud Run deployment.
FastAPI has no native SignalR host — Azure SignalR Service manages WebSocket
state and group membership on behalf of the backend.

REST API reference:
  POST https://{endpoint}/api/v1/hubs/{hub}/groups/{group}
  Authorization: Bearer <JWT signed with AccessKey>
  Body: {"target": "task_updated", "arguments": [{...}]}

US-022: broadcasts to three groups per event:
  - encounter-{encounter_id}
  - unit-{unit_id}
  - role-{role_name}
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import httpx
from app.signalr.schemas import BroadcastRequest, TaskUpdatedPayload

logger = logging.getLogger(__name__)

_HUB_NAME = "dashboard"
_TOKEN_TTL_SECONDS = 300


def _generate_access_token(endpoint: str, access_key: str, ttl: int = _TOKEN_TTL_SECONDS) -> str:
    """Generate a HS256 JWT for Azure SignalR Service REST API auth.

    Reference: Azure SignalR Service authentication for REST API
    (github.com/Azure/azure-signalr/blob/dev/docs/rest-api.md)
    """
    import jwt as pyjwt  # PyJWT

    audience = f"{endpoint}/api/v1/hubs/{_HUB_NAME}"
    payload = {
        "aud": audience,
        "exp": int(time.time()) + ttl,
    }
    return pyjwt.encode(payload, access_key, algorithm="HS256")


def _parse_connection_string(connection_string: str) -> tuple[str, str]:
    """Parse 'Endpoint=https://...;AccessKey=...;Version=1.0' format.

    Returns (endpoint_url, access_key).
    Raises ValueError if required keys are missing.
    """
    parts = dict(
        segment.split("=", 1)
        for segment in connection_string.split(";")
        if "=" in segment
    )
    endpoint = parts.get("Endpoint", "").rstrip("/")
    access_key = parts.get("AccessKey", "")
    if not endpoint or not access_key:
        raise ValueError("AZURE_SIGNALR_CONNECTION_STRING missing Endpoint or AccessKey")
    return endpoint, access_key


class SignalRBroadcaster:
    """Async broadcaster that sends group-scoped messages via Azure SignalR REST API.

    Instantiated once at application startup (lifespan context) and injected
    via FastAPI dependency injection.

    Usage:
        broadcaster = SignalRBroadcaster(connection_string)
        await broadcaster.broadcast_task_updated(payload)
    """

    def __init__(self, connection_string: str) -> None:
        self._endpoint, self._access_key = _parse_connection_string(connection_string)
        self._client = httpx.AsyncClient(timeout=5.0)

    async def aclose(self) -> None:
        """Close underlying HTTP client. Call in application shutdown lifespan."""
        await self._client.aclose()

    async def _send_to_group(self, group: str, target: str, arguments: list[dict]) -> None:
        """Low-level send to a SignalR group via Azure SignalR REST API."""
        body = BroadcastRequest(target=target, arguments=arguments)
        token = _generate_access_token(self._endpoint, self._access_key)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{self._endpoint}/api/v1/hubs/{_HUB_NAME}/groups/{quote(group, safe='')}"
        try:
            response = await self._client.post(url, json=body.model_dump(), headers=headers)
            response.raise_for_status()
            logger.info(
                "SignalR broadcast sent",
                extra={"group": group, "target": target},
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "SignalR broadcast HTTP error",
                extra={"group": group, "target": target, "status_code": exc.response.status_code},
            )
        except httpx.RequestError as exc:
            logger.warning(
                "SignalR broadcast request error",
                extra={"group": group, "target": target, "error": str(exc)},
            )

    async def broadcast_task_updated(self, payload: TaskUpdatedPayload) -> None:
        """Broadcast task_updated event to all three groups for the given task.

        Groups per US-022 DoD naming convention:
          - encounter-{encounter_id}
          - unit-{unit_id}
          - role-{role_name}

        Non-fatal: logs a WARNING on HTTP error so agent task status transitions
        are never blocked by SignalR broadcast failures.
        """
        groups = [
            f"encounter-{payload.encounter_id}",
            f"unit-{payload.unit_id}",
            f"role-{payload.role_name}",
        ]
        arguments = [payload.model_dump(mode="json")]
        for group in groups:
            await self._send_to_group(group, "task_updated", arguments)

    async def broadcast_adt_event(self, payload: dict) -> None:
        """Broadcast adt_event_received to a unit group.

        Used by dev/test endpoints and ADT ingestion pipeline.
        """
        unit_id = payload.get("patientUnit", "unknown")
        await self._send_to_group(f"unit-{unit_id}", "adt_event_received", [payload])

    async def broadcast_adt_event_to_all(self, payload: dict) -> None:
        """Broadcast adt_event_received to all connected clients.

        Used for dev smoke tests where group membership may not be configured.
        """
        body = BroadcastRequest(target="adt_event_received", arguments=[payload])
        token = _generate_access_token(self._endpoint, self._access_key)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{self._endpoint}/api/v1/hubs/{_HUB_NAME}"
        try:
            response = await self._client.post(url, json=body.model_dump(), headers=headers)
            response.raise_for_status()
            logger.info("SignalR broadcast to all sent", extra={"target": "adt_event_received"})
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "SignalR broadcast to all HTTP error",
                extra={"target": "adt_event_received", "status_code": exc.response.status_code},
            )
        except httpx.RequestError as exc:
            logger.warning(
                "SignalR broadcast to all request error",
                extra={"target": "adt_event_received", "error": str(exc)},
            )
