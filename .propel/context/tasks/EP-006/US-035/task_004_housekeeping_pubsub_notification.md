---
id: TASK-004
title: "Housekeeping Pub/Sub Notification on A03 Discharge"
user_story: US-035
epic: EP-006
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-035/TASK-001]
---

# TASK-004: Housekeeping Pub/Sub Notification on A03 Discharge

> **Story:** US-035 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-035 AC Scenario 2 and the DoD require that within **5 seconds** of an A03 discharge event, a housekeeping notification is published to the `notification-requests` Pub/Sub topic. The notification tells the housekeeping team which bed needs cleaning. An idempotency key prevents duplicate messages if the agent retries the event.

The `HousekeepingNotifier` is called by `BedManagementAgent.process()` (TASK-001) after the bed status DB write commits. Publishing to Pub/Sub is a non-transactional side effect and must not block the agent acknowledgement path beyond the 5-second SLA.

**Design references:**
- US-035 AC Scenario 2 — "housekeeping notification published within 5 seconds"
- US-035 DoD — "Housekeeping Pub/Sub notification: `notification-requests` topic within 5s of A03"
- design.md §7.5 (AIR-040) — Notification Service reads from `notification-requests` topic; idempotency key prevents duplicate sends
- design.md §3.1 — Notification Service dispatches housekeeping request
- BR-020 — PHI must not appear in Pub/Sub message payloads

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | A03 discharge → housekeeping notification published to `notification-requests` within 5 s |

---

## Implementation Steps

### 1. Define the notification payload schema

Add to `backend/app/agents/bed_management/schemas.py`:

```python
import hashlib


class HousekeepingNotificationPayload(BaseModel):
    """Payload published to the ``notification-requests`` Pub/Sub topic.

    Contains no PHI — only bed coordinates and event metadata.
    Idempotency key is a deterministic hash of ``bed_id + encounter_id``
    to prevent duplicate housekeeping requests if the agent retries A03.

    Design ref: AIR-040 — idempotency key prevents duplicate sends.
    """

    notification_type: Literal["HOUSEKEEPING_REQUIRED"] = "HOUSEKEEPING_REQUIRED"
    bed_id: str
    unit: str
    room: str
    bed_number: str
    encounter_id: str
    idempotency_key: str

    @classmethod
    def build(
        cls,
        bed_id: str,
        unit: str,
        room: str,
        bed_number: str,
        encounter_id: str,
    ) -> "HousekeepingNotificationPayload":
        """Construct the payload with a deterministic idempotency key.

        The key is SHA-256(bed_id + ":" + encounter_id), truncated to 32 hex chars.
        """
        raw = f"{bed_id}:{encounter_id}"
        idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return cls(
            bed_id=bed_id,
            unit=unit,
            room=room,
            bed_number=bed_number,
            encounter_id=encounter_id,
            idempotency_key=idempotency_key,
        )
```

### 2. Implement `backend/app/agents/bed_management/notifier.py`

```python
"""HousekeepingNotifier — publishes housekeeping requests to Pub/Sub on A03.

Published within 5 seconds of an A03 discharge event per US-035 AC Scenario 2.
Payload contains no PHI — only bed coordinates and a deterministic
idempotency key (bed_id + encounter_id hash).

Design refs:
    US-035 AC Scenario 2     — 5-second SLA for housekeeping notification
    US-035 DoD               — notification-requests Pub/Sub topic
    design.md §7.5 AIR-040   — idempotency key prevents duplicate sends
    BR-020                   — no PHI in Pub/Sub payloads
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bed_management.schemas import HousekeepingNotificationPayload
from app.models.bed import Bed

logger = logging.getLogger(__name__)

_TOPIC_ID = "notification-requests"


class HousekeepingNotifier:
    """Publishes a housekeeping notification to the ``notification-requests`` topic.

    Args:
        pubsub_client: Configured GCP Pub/Sub ``PublisherClient``.
        project_id: GCP project ID (read from Secret Manager / env var).
        read_session_factory: Async SQLAlchemy session factory bound to the
            read replica (used to look up bed coordinates: unit, room, bed_number).
    """

    def __init__(
        self,
        pubsub_client: Any,
        project_id: str,
        read_session_factory: Any,
    ) -> None:
        self._pubsub = pubsub_client
        self._topic_path = pubsub_client.topic_path(project_id, _TOPIC_ID)
        self._read_session_factory = read_session_factory

    async def notify(self, bed_id: str, encounter_id: str) -> None:
        """Publish a housekeeping notification for the given bed.

        Fetches bed coordinates (unit, room, bed_number) from the read replica,
        then publishes the notification. Failure is logged but not re-raised —
        the agent acknowledgement path must not be blocked.

        Args:
            bed_id: UUID string of the bed that requires cleaning.
            encounter_id: UUID string of the encounter that triggered A03.
        """
        try:
            bed = await self._fetch_bed_coordinates(bed_id)
            payload = HousekeepingNotificationPayload.build(
                bed_id=bed_id,
                unit=bed.unit,
                room=bed.room,
                bed_number=bed.bed_number,
                encounter_id=encounter_id,
            )
            await self._publish(payload)
            logger.info(
                "Housekeeping notification published bed_id=%s encounter_id=%s "
                "idempotency_key=%s",
                bed_id,
                encounter_id,
                payload.idempotency_key,
            )
        except Exception:
            logger.exception(
                "Failed to publish housekeeping notification bed_id=%s encounter_id=%s",
                bed_id,
                encounter_id,
            )

    async def _fetch_bed_coordinates(self, bed_id: str) -> Bed:
        """Load bed record from the read replica for coordinate lookup."""
        import uuid as _uuid

        async with self._read_session_factory() as session:
            result = await session.execute(
                select(Bed).where(Bed.id == _uuid.UUID(bed_id))
            )
            bed = result.scalar_one_or_none()
            if bed is None:
                raise ValueError(f"Bed not found for housekeeping notification: {bed_id}")
            return bed

    async def _publish(self, payload: HousekeepingNotificationPayload) -> None:
        """Publish JSON-encoded payload to the ``notification-requests`` topic."""
        data = json.dumps(payload.model_dump()).encode("utf-8")
        # Pub/Sub attributes for message filtering by the Notification Service
        attributes = {
            "notification_type": payload.notification_type,
            "idempotency_key": payload.idempotency_key,
        }
        future = self._pubsub.publish(self._topic_path, data, **attributes)
        future.result(timeout=5)  # enforce 5-second SLA (US-035 AC Scenario 2)
```

### 3. Wire `HousekeepingNotifier` into `main.py`

Update `backend/app/agents/bed_management/main.py`:

```python
from app.agents.bed_management.notifier import HousekeepingNotifier
from app.core.config import settings
from app.core.dependencies import get_pubsub_client, get_read_db

housekeeping_notifier = HousekeepingNotifier(
    pubsub_client=get_pubsub_client(),
    project_id=settings.GCP_PROJECT_ID,
    read_session_factory=get_read_db,
)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/bed_management/schemas.py` | Update — add `HousekeepingNotificationPayload` |
| `backend/app/agents/bed_management/notifier.py` | Create |
| `backend/app/agents/bed_management/main.py` | Update — inject `HousekeepingNotifier` |

---

## Validation

- [ ] `HousekeepingNotificationPayload.build(bed_id, unit, room, bed_number, encounter_id)` produces deterministic `idempotency_key`
- [ ] Calling `build()` twice with the same inputs produces the same `idempotency_key`
- [ ] Pub/Sub publish uses `future.result(timeout=5)` — enforces 5-second SLA
- [ ] Publish failure logs exception but does NOT propagate — agent acknowledgement is not blocked
- [ ] No PHI in payload or log lines — only `bed_id`, `encounter_id`, `unit`, `room`, `bed_number`
- [ ] `notification_type` attribute is set on the Pub/Sub message for downstream filtering

---

## Definition of Done

- [ ] `HousekeepingNotifier` implemented with idempotency key and 5-second timeout
- [ ] Notifier wired into `BedManagementAgent` A03 handling path (TASK-001)
- [ ] No PHI in Pub/Sub payload or application logs
- [ ] Code peer-reviewed before merge
