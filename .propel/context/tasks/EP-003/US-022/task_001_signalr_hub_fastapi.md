---
id: TASK-001
title: "Implement FastAPI SignalR Broadcast Endpoint `POST /api/v1/signalr/task-updated` via Azure SignalR Service REST API"
user_story: US-022
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-021/TASK-005]
---

# TASK-001: Implement FastAPI SignalR Broadcast Endpoint `POST /api/v1/signalr/task-updated` via Azure SignalR Service REST API

> **Story:** US-022 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-022 DoD requires:

> *"FastAPI SignalR hub implemented: `POST /api/v1/signalr/task-updated` broadcasts to correct groups"*
> *"Group naming convention: `encounter-{id}`, `unit-{unitId}`, `role-{roleName}`"*

FastAPI has no native SignalR runtime. Per the US-022 Technical Notes, the chosen approach is the **Azure SignalR Service REST API** — a stateless broadcast model where the FastAPI backend POSTs a broadcast message to the Azure SignalR Service endpoint. Azure SignalR maintains WebSocket connections with Angular clients, removing the burden of managing WebSocket state from the stateless Cloud Run container.

This task creates:
1. `SignalRBroadcaster` — a thin async HTTP client that wraps the Azure SignalR REST API.
2. `POST /api/v1/signalr/task-updated` FastAPI router endpoint that validates the incoming payload and delegates broadcast to `SignalRBroadcaster`.
3. GCP Secret Manager integration for the Azure SignalR connection string.
4. Unit tests mocking the Azure SignalR REST API.

---

## Acceptance Criteria Addressed

| US-022 AC | Requirement |
|---|---|
| **Scenario 1** | `task_updated` event delivered to all subscribed clients after backend DB write |
| **Scenario 2** | Broadcasts routed to `encounter-{id}`, `unit-{unitId}`, `role-{roleName}` groups |
| **DoD** | `POST /api/v1/signalr/task-updated` endpoint implemented and broadcasts to correct groups |

---

## Implementation Steps

### 1. Service directory structure

This task creates the following files under the existing FastAPI backend service:

```
backend/
├── app/
│   ├── signalr/
│   │   ├── __init__.py
│   │   ├── broadcaster.py           ← THIS TASK
│   │   └── schemas.py               ← THIS TASK
│   ├── routers/
│   │   └── signalr_hub.py           ← THIS TASK
│   └── config/
│       └── settings.py              ← add AZURE_SIGNALR_CONNECTION_STRING
└── tests/
    └── unit/
        └── signalr/
            └── test_broadcaster.py  ← THIS TASK
```

```bash
mkdir -p backend/app/signalr
mkdir -p backend/tests/unit/signalr
touch backend/app/signalr/__init__.py
```

### 2. Create `backend/app/signalr/schemas.py`

```python
"""Pydantic request/response schemas for the SignalR hub broadcast endpoint.

US-022 DoD: POST /api/v1/signalr/task-updated
Group naming convention: encounter-{id}, unit-{unitId}, role-{roleName}
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# Matches the AgentTask status enum from US-020/US-021.
AgentTaskStatus = Literal["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "ESCALATED"]


class TaskUpdatedPayload(BaseModel):
    """Payload sent by agents after each status transition.

    Fields forwarded verbatim inside the SignalR `task_updated` event data.
    US-022 Scenario 1: status field captures IN_PROGRESS → COMPLETED transitions.
    """

    task_id: UUID = Field(..., description="AgentTask primary key")
    encounter_id: UUID = Field(..., description="Parent encounter; maps to group encounter-{id}")
    unit_id: str = Field(..., description="Hospital unit; maps to group unit-{unitId}")
    role_name: str = Field(..., description="Target clinical role; maps to group role-{roleName}")
    agent_type: str = Field(..., description="Agent that changed state, e.g. DOCUMENTATION")
    previous_status: AgentTaskStatus
    new_status: AgentTaskStatus
    updated_at: datetime = Field(..., description="Timestamp of DB write — used for latency tracking")


class BroadcastRequest(BaseModel):
    """Internal broadcast request forwarded to Azure SignalR REST API.

    target: SignalR event name received by Angular HubConnection.on('task_updated', ...)
    arguments: single-element list containing the serialised TaskUpdatedPayload.
    """

    target: str = "task_updated"
    arguments: list[dict]
```

### 3. Create `backend/app/signalr/broadcaster.py`

```python
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

import hashlib
import hmac
import logging
import time
from base64 import b64decode, b64encode
from typing import Any
from urllib.parse import quote, urlparse

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
        body = BroadcastRequest(
            target="task_updated",
            arguments=[payload.model_dump(mode="json")],
        )
        token = _generate_access_token(self._endpoint, self._access_key)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        for group in groups:
            url = f"{self._endpoint}/api/v1/hubs/{_HUB_NAME}/groups/{quote(group, safe='')}"
            try:
                response = await self._client.post(url, json=body.model_dump(), headers=headers)
                response.raise_for_status()
                logger.info(
                    "SignalR broadcast sent",
                    extra={
                        "task_id": str(payload.task_id),
                        "group": group,
                        "new_status": payload.new_status,
                    },
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "SignalR broadcast HTTP error",
                    extra={
                        "task_id": str(payload.task_id),
                        "group": group,
                        "status_code": exc.response.status_code,
                    },
                )
            except httpx.RequestError as exc:
                logger.warning(
                    "SignalR broadcast request error",
                    extra={"task_id": str(payload.task_id), "group": group, "error": str(exc)},
                )
```

### 4. Create `backend/app/routers/signalr_hub.py`

```python
"""Router: POST /api/v1/signalr/task-updated

Internal broadcast endpoint called by AI agents after each AgentTask status
transition. Validates the payload and delegates to SignalRBroadcaster.

Security:
  - Requires a valid service-to-service JWT (internal scope claim).
  - Not exposed through Cloud Armor to public internet — ingress restricted to
    Cloud Run internal traffic only (VPC connector).

US-022 DoD:
  - POST /api/v1/signalr/task-updated broadcasts to correct groups.
  - Group naming: encounter-{id}, unit-{unitId}, role-{roleName}.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response

from app.auth.dependencies import get_current_internal_service
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import TaskUpdatedPayload
from app.dependencies import get_signalr_broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signalr", tags=["signalr"])


@router.post(
    "/task-updated",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Broadcast AgentTask status update to SignalR groups",
    description=(
        "Called by AI agents after each status transition. "
        "Broadcasts task_updated event to encounter-{id}, unit-{unitId}, role-{roleName} groups."
    ),
)
async def broadcast_task_updated(
    payload: TaskUpdatedPayload,
    _caller: Annotated[None, Depends(get_current_internal_service)],
    broadcaster: Annotated[SignalRBroadcaster, Depends(get_signalr_broadcaster)],
) -> Response:
    """Broadcast task_updated to all three SignalR groups.

    Returns 202 Accepted immediately — broadcast is fire-and-forget.
    Broadcast errors are logged but never returned as 5xx to the caller
    so that agent task updates are never blocked by SignalR failures.
    """
    logger.info(
        "Received task-updated broadcast request",
        extra={
            "task_id": str(payload.task_id),
            "encounter_id": str(payload.encounter_id),
            "new_status": payload.new_status,
        },
    )
    await broadcaster.broadcast_task_updated(payload)
    return Response(status_code=status.HTTP_202_ACCEPTED)
```

### 5. Add `SignalRBroadcaster` to application lifespan in `backend/app/main.py`

```python
# In the existing lifespan context manager, add broadcaster init/cleanup:

from contextlib import asynccontextmanager
from app.signalr.broadcaster import SignalRBroadcaster
from app.config.settings import settings

_broadcaster: SignalRBroadcaster | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcaster
    _broadcaster = SignalRBroadcaster(settings.azure_signalr_connection_string)
    yield
    if _broadcaster:
        await _broadcaster.aclose()


# Dependency provider — add to backend/app/dependencies.py
def get_signalr_broadcaster() -> SignalRBroadcaster:
    """FastAPI dependency: returns the singleton SignalRBroadcaster."""
    if _broadcaster is None:
        raise RuntimeError("SignalRBroadcaster not initialised — check lifespan setup")
    return _broadcaster
```

### 6. Add `AZURE_SIGNALR_CONNECTION_STRING` to settings

```python
# backend/app/config/settings.py — add to existing Settings class:

class Settings(BaseSettings):
    # ... existing fields ...

    # Azure SignalR Service connection string.
    # Format: Endpoint=https://<name>.service.signalr.net;AccessKey=<key>;Version=1.0
    # Sourced from GCP Secret Manager via environment variable injection at Cloud Run startup.
    azure_signalr_connection_string: str = Field(
        ...,
        description="Azure SignalR Service connection string from GCP Secret Manager",
    )
```

### 7. Register router in `backend/app/main.py`

```python
from app.routers.signalr_hub import router as signalr_router

app.include_router(signalr_router, prefix="/api/v1")
```

### 8. Create `backend/tests/unit/signalr/test_broadcaster.py`

```python
"""Unit tests for SignalRBroadcaster.

Tests mock httpx.AsyncClient — no live Azure SignalR calls.
Coverage targets:
  - Correct group names constructed (US-022 DoD naming convention)
  - HTTP error logged as WARNING; no exception raised to caller
  - Connection string parse errors raise ValueError
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from app.signalr.broadcaster import SignalRBroadcaster, _parse_connection_string
from app.signalr.schemas import TaskUpdatedPayload


VALID_CONN_STR = (
    "Endpoint=https://test.service.signalr.net;"
    "AccessKey=dGVzdGtleQ==;"
    "Version=1.0"
)


def _make_payload(**kwargs) -> TaskUpdatedPayload:
    defaults = dict(
        task_id=uuid4(),
        encounter_id=uuid4(),
        unit_id="3A",
        role_name="pharmacist",
        agent_type="MEDICATION_RECONCILIATION",
        previous_status="IN_PROGRESS",
        new_status="COMPLETED",
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return TaskUpdatedPayload(**defaults)


class TestParseConnectionString:
    def test_valid_connection_string_returns_endpoint_and_key(self):
        endpoint, key = _parse_connection_string(VALID_CONN_STR)
        assert endpoint == "https://test.service.signalr.net"
        assert key == "dGVzdGtleQ=="

    def test_missing_access_key_raises_value_error(self):
        with pytest.raises(ValueError, match="AccessKey"):
            _parse_connection_string("Endpoint=https://test.service.signalr.net;Version=1.0")

    def test_missing_endpoint_raises_value_error(self):
        with pytest.raises(ValueError, match="Endpoint"):
            _parse_connection_string("AccessKey=abc;Version=1.0")


class TestSignalRBroadcaster:
    @pytest.mark.asyncio
    async def test_broadcast_calls_three_groups(self):
        """Verifies encounter-, unit-, and role- groups all receive a POST."""
        broadcaster = SignalRBroadcaster(VALID_CONN_STR)
        payload = _make_payload()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch.object(broadcaster._client, "post", new=AsyncMock(return_value=mock_response)) as mock_post:
            await broadcaster.broadcast_task_updated(payload)

        assert mock_post.call_count == 3
        urls = [call.args[0] for call in mock_post.call_args_list]
        assert any(f"encounter-{payload.encounter_id}" in u for u in urls)
        assert any("unit-3A" in u for u in urls)
        assert any("role-pharmacist" in u for u in urls)
        await broadcaster.aclose()

    @pytest.mark.asyncio
    async def test_http_error_logged_not_raised(self, caplog):
        """HTTP 500 from Azure SignalR is logged as WARNING — caller is not interrupted."""
        import httpx
        broadcaster = SignalRBroadcaster(VALID_CONN_STR)
        payload = _make_payload()

        error_response = MagicMock(status_code=500)
        http_error = httpx.HTTPStatusError("500", request=MagicMock(), response=error_response)

        with patch.object(broadcaster._client, "post", new=AsyncMock(side_effect=http_error)):
            with caplog.at_level("WARNING", logger="app.signalr.broadcaster"):
                await broadcaster.broadcast_task_updated(payload)  # must not raise

        assert "SignalR broadcast HTTP error" in caplog.text
        await broadcaster.aclose()
```

---

## Validation Loop

Before marking this task complete, verify:

```bash
# Run unit tests
pytest backend/tests/unit/signalr/ -v

# Confirm router is registered
python -c "from app.main import app; routes = [r.path for r in app.routes]; assert '/api/v1/signalr/task-updated' in routes, 'Route missing'"

# Confirm settings loads from env
AZURE_SIGNALR_CONNECTION_STRING="Endpoint=https://x.service.signalr.net;AccessKey=abc;Version=1.0" \
  python -c "from app.config.settings import settings; print(settings.azure_signalr_connection_string)"
```

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `httpx` | PyPI | Async HTTP client; already in backend `requirements.txt` |
| `PyJWT` | PyPI | HS256 token generation for Azure SignalR REST auth — add to `requirements.txt` |
| `AZURE_SIGNALR_CONNECTION_STRING` | GCP Secret Manager | Provisioned by TASK-002; injected at Cloud Run startup |
| US-021/TASK-005 | Upstream story | `AgentTask` status schema and encounter router patterns reused |
