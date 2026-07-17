---
id: TASK-003
title: "BoardingAlertPublisher — Pub/Sub Dispatch with Idempotency Guard"
user_story: US-038
epic: EP-006
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-038/TASK-001, US-038/TASK-002]
---

# TASK-003: BoardingAlertPublisher — Pub/Sub Dispatch with Idempotency Guard

> **Story:** US-038 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-038 AC Scenario 1 requires that a boarding alert be published to the `notification-requests` Pub/Sub topic with `priority=IMMEDIATE` when a patient has been in the ED for ≥120 minutes without a bed assignment.

US-038 AC Scenario 4 requires strict idempotency: if `boarding_alert_sent_at` is already set on the encounter, no second alert may be published for that ED stay.

The `BoardingAlertPublisher` receives a list of `BoardingCandidate` instances from the `BoardingMonitor` (TASK-002) and, for each:

1. **Checks idempotency** — skips if `candidate.already_alerted` is `True`.
2. **Constructs the `BoardingAlertPayload`** — no PHI beyond opaque UUIDs (BR-020, AIR-040).
3. **Publishes to Pub/Sub** `notification-requests` topic with `priority=IMMEDIATE`.
4. **Writes `boarding_alert_sent_at`** to the `encounter` row in a DB transaction after successful publish. The DB write is the authoritative record; the Pub/Sub publish is the side effect.

The idempotency key (`boarding:{encounter_id}:{boarding_start_iso}`) is included in the Pub/Sub message attributes so the downstream Notification Service can deduplicate at its layer too (AIR-040).

**Design references:**
- US-038 AC Scenario 1 — payload fields: `priority=HIGH` (note: Technical Notes override to `priority=IMMEDIATE`), `patient_id`, `ed_arrival_time`, `minutes_elapsed`, `target_unit`
- US-038 AC Scenario 4 — idempotency key; `boarding_alert_sent_at` set after publish
- US-038 Technical Notes — "boarding alerts must have `priority=IMMEDIATE` in Pub/Sub `notification-requests`"
- design.md §7.5 (AIR-040) — idempotency key prevents duplicate sends; Notification Service reads from `notification-requests`
- design.md §7.5 (AIR-041) — Twilio webhook updates delivery status (downstream; not in scope here)
- BR-020 — no PHI in Pub/Sub payloads

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Alert published to `notification-requests` with `priority=IMMEDIATE` and all required fields |
| Scenario 4 | `boarding_alert_sent_at` already set → skip publish; no duplicate message |

---

## Implementation Steps

### 1. Create publisher module

```bash
touch backend/app/agents/bed_management/boarding_publisher.py
```

### 2. Implement `backend/app/agents/bed_management/boarding_publisher.py`

```python
"""BoardingAlertPublisher — dispatches boarding alerts to Pub/Sub with idempotency.

Receives ``BoardingCandidate`` instances from ``BoardingMonitor`` and, for each
un-alerted encounter, publishes a ``BoardingAlertPayload`` to the
``notification-requests`` Pub/Sub topic, then sets ``boarding_alert_sent_at``
on the encounter record.

Idempotency strategy:
    1. In-memory check: ``candidate.already_alerted`` (fast path, no DB hit).
    2. DB-level guard: UPDATE ... WHERE boarding_alert_sent_at IS NULL ensures
       exactly-once write even under concurrent monitor instances.

Design refs:
    US-038 AC Scenario 1   — priority=IMMEDIATE, payload structure
    US-038 AC Scenario 4   — idempotency; boarding_alert_sent_at set after publish
    design.md §7.5 AIR-040 — notification-requests topic; idempotency_key attribute
    BR-020                 — no PHI in Pub/Sub payloads (patient_id is opaque UUID)
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from google.cloud import pubsub_v1
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bed_management.boarding_schemas import BoardingAlertPayload, BoardingCandidate
from app.core.config import settings
from app.models.encounter import Encounter

logger = logging.getLogger(__name__)

# Type alias for the session factory injected at construction time
SessionFactory = Callable[[], Coroutine[Any, Any, AsyncSession]]


class BoardingAlertPublisher:
    """Publishes ED boarding alerts to ``notification-requests`` with idempotency.

    Args:
        pubsub_client: Initialised ``google.cloud.pubsub_v1.PublisherClient``.
        db_session_factory: Async context manager factory returning an ``AsyncSession``
                            scoped to the write (primary) DB.
        topic_path: Override for the Pub/Sub topic path. Defaults to
                    ``projects/{project_id}/topics/notification-requests``.
    """

    def __init__(
        self,
        pubsub_client: pubsub_v1.PublisherClient,
        db_session_factory: SessionFactory,
        topic_path: str | None = None,
    ) -> None:
        self._client = pubsub_client
        self._session_factory = db_session_factory
        self._topic_path = topic_path or pubsub_v1.PublisherClient.topic_path(
            settings.GCP_PROJECT_ID, "notification-requests"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch_alerts(self, candidates: list[BoardingCandidate]) -> None:
        """Dispatch boarding alerts for all un-alerted candidates.

        Args:
            candidates: List produced by ``BoardingMonitor._detect_boarding_candidates()``.
                        May contain already-alerted encounters (idempotency check filters them).
        """
        for candidate in candidates:
            # Fast-path idempotency check (no DB round-trip needed when field is set)
            if candidate.already_alerted:
                logger.debug(
                    "Skipping boarding alert for encounter %s — already sent at %s.",
                    candidate.encounter_id,
                    candidate.boarding_alert_sent_at,
                )
                continue
            await self._publish_single(candidate)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _publish_single(self, candidate: BoardingCandidate) -> None:
        """Publish one boarding alert and record the send timestamp in the DB.

        Order of operations:
            1. Build the payload.
            2. Publish to Pub/Sub (non-transactional side effect).
            3. Write boarding_alert_sent_at to DB — WHERE boarding_alert_sent_at IS NULL
               ensures exactly-once even under concurrent monitor instances (DB-level guard).

        If Pub/Sub publish fails, no DB write is made so the next cycle will retry.
        """
        payload = BoardingAlertPayload(
            patient_id=candidate.patient_id,
            encounter_id=candidate.encounter_id,
            ed_arrival_time=candidate.ed_arrival_time.isoformat(),
            minutes_elapsed=candidate.minutes_elapsed,
            target_unit=candidate.target_unit,
            idempotency_key=candidate.idempotency_key,
        )

        # --- Pub/Sub publish ---
        message_data = json.dumps(payload.model_dump()).encode("utf-8")
        attributes = {
            "notification_type": "ED_BOARDING_ALERT",
            "priority": "IMMEDIATE",
            "idempotency_key": candidate.idempotency_key,
        }
        try:
            future = self._client.publish(
                self._topic_path, data=message_data, **attributes
            )
            message_id = future.result(timeout=10)
            logger.info(
                "Boarding alert published: encounter=%s message_id=%s minutes_elapsed=%d",
                candidate.encounter_id,
                message_id,
                candidate.minutes_elapsed,
            )
        except Exception:
            logger.exception(
                "Failed to publish boarding alert for encounter %s — will retry next cycle.",
                candidate.encounter_id,
            )
            return  # Do NOT write boarding_alert_sent_at — allow retry next cycle

        # --- DB write (exactly-once guard) ---
        now_utc = datetime.now(UTC)
        async with self._session_factory() as session:  # type: AsyncSession
            result = await session.execute(
                update(Encounter)
                .where(
                    Encounter.id == candidate.encounter_id,
                    Encounter.boarding_alert_sent_at.is_(None),  # DB-level idempotency
                )
                .values(boarding_alert_sent_at=now_utc)
                .returning(Encounter.id)
            )
            if result.rowcount == 0:
                # Another instance already wrote boarding_alert_sent_at — safe to ignore
                logger.info(
                    "boarding_alert_sent_at already set by concurrent instance for encounter %s.",
                    candidate.encounter_id,
                )
            await session.commit()
```

### 3. Verify payload structure satisfies AC Scenario 1 fields

The `BoardingAlertPayload` produced must include all fields required by US-038 AC Scenario 1:

| AC Field | Payload Field | Value Source |
|---|---|---|
| `priority=HIGH` (overridden by Technical Notes to `IMMEDIATE`) | `priority` | Hard-coded `"IMMEDIATE"` |
| `patient_id` | `patient_id` | `BoardingCandidate.patient_id` (UUID) |
| `ed_arrival_time` | `ed_arrival_time` | `BoardingCandidate.ed_arrival_time.isoformat()` |
| `minutes_elapsed=120` | `minutes_elapsed` | `BoardingCandidate.minutes_elapsed` |
| `target_unit` | `target_unit` | `enc.admission_unit` (may be `None`) |
| (not in AC) | `idempotency_key` | `boarding:{encounter_id}:{ed_arrival_time_iso}` |
| (not in AC) | `notification_type` | `"ED_BOARDING_ALERT"` |

> **Note on `priority` field:** US-038 AC Scenario 1 specifies `priority=HIGH` in the acceptance criteria but the Technical Notes section explicitly states *"boarding alerts must have `priority=IMMEDIATE`"*. The implementation uses `IMMEDIATE` per the Technical Notes as the more specific constraint.

---

## Validation Checklist

- [ ] `dispatch_alerts()` skips candidates where `candidate.already_alerted` is `True`
- [ ] `_publish_single()` does NOT write `boarding_alert_sent_at` if Pub/Sub publish fails
- [ ] DB UPDATE uses `WHERE boarding_alert_sent_at IS NULL` — concurrent-safe
- [ ] Payload includes `idempotency_key` as both a payload field and a Pub/Sub message attribute
- [ ] `priority=IMMEDIATE` in both payload and Pub/Sub attributes
- [ ] No PHI fields (name, DOB, MRN, phone) in payload or Pub/Sub attributes
- [ ] `future.result(timeout=10)` — Pub/Sub publish has a hard timeout to avoid blocking the cycle

---

## Files Changed

| File | Action |
|---|---|
| `backend/app/agents/bed_management/boarding_publisher.py` | Create |
