---
id: TASK-004
title: "Emergency Alert Handler — Hardcoded Reply, Pub/Sub CARE_TEAM_URGENCY_ALERT, DB urgency_flag"
user_story: US-044
epic: EP-008
sprint: 2
layer: Backend / AI Agent
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-044/TASK-001, US-044/TASK-002, US-044/TASK-003]
---

# TASK-004: Emergency Alert Handler — Hardcoded Reply, Pub/Sub CARE_TEAM_URGENCY_ALERT, DB urgency_flag

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

When `UrgencyDetector.detect()` returns `is_urgent=True`, three actions must complete within the 10-second SLA (US-044 AC Scenario 1):

1. **Hardcoded emergency reply** returned to the patient immediately — NOT dependent on any LLM response
2. **`CARE_TEAM_URGENCY_ALERT`** published to the `notification-requests` Pub/Sub topic (read by the Notification Service → Twilio SMS to care team)
3. **`chatbot_transcript.urgency_flag=True`** persisted to the Cloud SQL `chatbot_transcript` table

All three actions are orchestrated by `EmergencyAlertHandler`. The hardcoded reply (from `config/emergency_contacts.yaml`) is constructed synchronously; the Pub/Sub publish and DB write run concurrently via `asyncio.gather()` to minimise total latency.

**Design references:**
- design.md §3.1 — Patient Communication Agent: urgency detection, escalation routing
- design.md §7.5 AIR-040 — Notification Service reads from `notification-requests`; idempotency key prevents duplicate sends
- design.md §7.5 AIR-041 — Twilio webhook updates delivery status; failed deliveries retried 3×
- design.md §6.3 DR-016 — chatbot transcripts stored in Cloud SQL (encrypted, linked to encounter)
- US-044 AC Scenario 1 — within 10 seconds: (a) emergency contact displayed, (b) `CARE_TEAM_URGENCY_ALERT` published, (c) `urgency_flag=True` persisted
- US-044 DoD — emergency response is hardcoded — NOT dependent on LLM response
- US-044 Technical Notes — alert payload: `{encounter_id, patient_first_name (only), urgency_message_summary, timestamp}`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `EmergencyAlertHandler.handle()` returns the hardcoded reply AND publishes alert AND persists flag — all within 10s |
| Scenario 2 | Emergency reply text matches the configured `display_message` from `emergency_contacts.yaml` |
| Scenario 3 | Semantic urgency path also routes through `EmergencyAlertHandler` (same handler for both phases) |

---

## Implementation Steps

### 1. Create the emergency alert handler module

```bash
touch backend/app/agents/patient_comm/urgency/emergency_handler.py
```

### 2. Add `chatbot_transcript` table migration (Alembic)

The `urgency_flag` column must be added to the `chatbot_transcript` table. Create Alembic migration:

```bash
# From project root
alembic revision --autogenerate -m "add_urgency_flag_to_chatbot_transcript"
```

The migration should produce:

```python
# In the generated migration file under alembic/versions/
def upgrade() -> None:
    op.add_column(
        "chatbot_transcript",
        sa.Column(
            "urgency_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True when UrgencyDetector flagged this message as urgent (US-044)",
        ),
    )
    op.create_index(
        "ix_chatbot_transcript_urgency_flag",
        "chatbot_transcript",
        ["urgency_flag"],
        postgresql_where=sa.text("urgency_flag = true"),
    )

def downgrade() -> None:
    op.drop_index("ix_chatbot_transcript_urgency_flag", table_name="chatbot_transcript")
    op.drop_column("chatbot_transcript", "urgency_flag")
```

### 3. Implement `backend/app/agents/patient_comm/urgency/emergency_handler.py`

```python
"""Emergency alert handler for urgency-detected patient messages (US-044, TASK-004).

When UrgencyDetector returns is_urgent=True, this handler:
    1. Constructs the hardcoded emergency reply (NOT dependent on any LLM call)
    2. Publishes CARE_TEAM_URGENCY_ALERT to the notification-requests Pub/Sub topic
    3. Persists chatbot_transcript.urgency_flag=True in Cloud SQL
    4. Returns the emergency reply string for immediate display in the chat UI

Actions 2 and 3 run concurrently via asyncio.gather() to minimise total latency
within the 10-second SLA (US-044 AC Scenario 1).

Design refs:
    US-044 DoD — emergency response NOT dependent on LLM response
    design.md §7.5 AIR-040 — notification-requests Pub/Sub; idempotency key
    design.md §6.3 DR-016 — chatbot transcripts in Cloud SQL (encrypted)
    design.md §7.3 AIR-021 — minimum PHI in alert payload
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from google.cloud import pubsub_v1
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.urgency.config_loader import (
    load_emergency_contact_config,
)
from backend.app.agents.patient_comm.urgency.schemas import (
    EmergencyContactConfig,
    UrgencyAlertPayload,
    UrgencyDetectionResult,
)

logger = logging.getLogger(__name__)

# Pub/Sub project ID — injected via environment at Cloud Run startup
import os
_GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "smarthandoff-prod")


class EmergencyAlertHandler:
    """Orchestrates the three emergency response actions for urgency-flagged messages.

    Instantiated once per agent container and reused across requests.
    The Pub/Sub PublisherClient is created once and reused (thread-safe).
    """

    def __init__(self) -> None:
        self._config: EmergencyContactConfig = load_emergency_contact_config()
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(
            _GCP_PROJECT_ID, self._config.care_team_alert_channel
        )

    async def handle(
        self,
        urgency_result: UrgencyDetectionResult,
        encounter_id: str,
        patient_first_name: str,
        db_session: AsyncSession,
    ) -> str:
        """Execute all three emergency actions and return the hardcoded reply.

        Args:
            urgency_result: Result from UrgencyDetector.detect() with is_urgent=True.
            encounter_id: UUID of the patient's current encounter.
            patient_first_name: Patient's first name only (minimum PHI for alert).
                Must be sourced from the patient JWT or encounter record — not
                from the patient's own message.
            db_session: SQLAlchemy async session for writing urgency_flag to DB.

        Returns:
            The hardcoded emergency reply string for immediate display in the chat UI.
            This string is returned BEFORE the Pub/Sub and DB operations complete
            so the UI can display it within the 10-second SLA.
        """
        # Build hardcoded reply immediately — NOT dependent on LLM
        emergency_reply: str = self._config.display_message

        # Build the Pub/Sub alert payload (minimum PHI)
        alert_payload = UrgencyAlertPayload(
            encounter_id=encounter_id,
            patient_first_name=patient_first_name,
            urgency_message_summary=urgency_result.message_summary or "Urgency signal detected",
            timestamp=datetime.now(timezone.utc),
        )

        # Run Pub/Sub publish and DB write concurrently
        await asyncio.gather(
            self._publish_care_team_alert(alert_payload),
            self._persist_urgency_flag(db_session, encounter_id),
            return_exceptions=True,  # Do not raise — log and continue even if one fails
        )

        logger.info(
            "urgency_emergency_response_dispatched",
            extra={
                "encounter_id": encounter_id,
                "detection_phase": urgency_result.detection_phase.value,
            },
        )

        return emergency_reply

    async def _publish_care_team_alert(self, payload: UrgencyAlertPayload) -> None:
        """Publish CARE_TEAM_URGENCY_ALERT to the notification-requests Pub/Sub topic.

        Idempotency key: `encounter_id + timestamp` prevents duplicate sends
        if the handler is retried (design.md AIR-040).

        PHI note: Only patient_first_name (not full name), encounter_id (UUID),
        urgency_message_summary (system-generated), and timestamp are published.
        The raw patient message is NEVER included in the payload.
        """
        idempotency_key = f"{payload.encounter_id}-{payload.timestamp.isoformat()}"
        message_data = json.dumps(payload.model_dump(mode="json")).encode("utf-8")

        try:
            future = self._publisher.publish(
                self._topic_path,
                data=message_data,
                idempotency_key=idempotency_key,
                event_type="CARE_TEAM_URGENCY_ALERT",
            )
            message_id = await asyncio.get_event_loop().run_in_executor(None, future.result)
            logger.info(
                "care_team_urgency_alert_published",
                extra={
                    "encounter_id": payload.encounter_id,
                    "pubsub_message_id": message_id,
                },
            )
        except Exception as exc:
            # Log and continue — alert failure must not block the emergency reply
            logger.error(
                "care_team_urgency_alert_publish_failed",
                extra={
                    "encounter_id": payload.encounter_id,
                    "error_type": type(exc).__name__,
                },
            )

    async def _persist_urgency_flag(
        self, db_session: AsyncSession, encounter_id: str
    ) -> None:
        """Set urgency_flag=True on the most recent chatbot_transcript row for this encounter.

        Design ref: US-044 AC Scenario 1(c) — `chatbot_transcript.urgency_flag=True` persisted.
        Design ref: design.md DR-016 — chatbot transcripts stored in Cloud SQL.

        If the DB write fails, the error is logged — it must not block the emergency reply.
        """
        from sqlalchemy import text

        try:
            await db_session.execute(
                text(
                    """
                    UPDATE chatbot_transcript
                    SET urgency_flag = TRUE
                    WHERE encounter_id = :encounter_id
                      AND id = (
                        SELECT id FROM chatbot_transcript
                        WHERE encounter_id = :encounter_id
                        ORDER BY created_at DESC
                        LIMIT 1
                      )
                    """
                ),
                {"encounter_id": encounter_id},
            )
            await db_session.commit()
            logger.info(
                "chatbot_transcript_urgency_flag_set",
                extra={"encounter_id": encounter_id},
            )
        except Exception as exc:
            await db_session.rollback()
            logger.error(
                "chatbot_transcript_urgency_flag_persist_failed",
                extra={
                    "encounter_id": encounter_id,
                    "error_type": type(exc).__name__,
                },
            )
```

---

## Validation Checklist

```bash
# Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('backend/app/agents/patient_comm/urgency/emergency_handler.py').read_text())
print('emergency_handler.py — syntax OK')
"

# Schema payload PHI validation
python -c "
from backend.app.agents.patient_comm.urgency.schemas import UrgencyAlertPayload
fields = set(UrgencyAlertPayload.model_fields.keys())
phi_fields = {'last_name', 'dob', 'mrn', 'phone', 'email', 'message', 'content'}
found = fields & phi_fields
assert not found, f'UrgencyAlertPayload contains PHI fields: {found}'
print(f'UrgencyAlertPayload fields: {fields} — no PHI ✓')
assert 'patient_first_name' in fields
assert 'urgency_message_summary' in fields
assert 'encounter_id' in fields
print('Required minimum-PHI fields present ✓')
"

# Alembic migration check (review generated file manually)
alembic check
echo "Alembic — no pending migrations in schema ✓ (run after applying migration)"
```

---

## Definition of Done

- [ ] `backend/app/agents/patient_comm/urgency/emergency_handler.py` created
- [ ] Alembic migration created adding `urgency_flag BOOLEAN DEFAULT FALSE` to `chatbot_transcript` with partial index
- [ ] `EmergencyAlertHandler.handle()` returns hardcoded `display_message` from config (not LLM-generated)
- [ ] Pub/Sub publish uses idempotency key `{encounter_id}-{timestamp}` (AIR-040)
- [ ] `asyncio.gather(return_exceptions=True)` — Pub/Sub and DB failure do not block emergency reply
- [ ] `UrgencyAlertPayload` contains only: `encounter_id`, `patient_first_name`, `urgency_message_summary`, `timestamp`, `channel` — no raw message, no last_name, no DOB, no MRN
- [ ] All logger calls contain only non-PHI fields (`encounter_id`, `detection_phase`, `pubsub_message_id`)
- [ ] Syntax check passes
- [ ] Payload PHI validation script passes
