---
id: TASK-004
title: "FollowUpCareAgent Extension — Care Pathway Activation & HIGH-Risk Pub/Sub Alert"
user_story: US-040
epic: EP-007
sprint: 2
layer: Backend / AI Agent
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-039/TASK-004, US-040/TASK-001, US-040/TASK-002, US-040/TASK-003]
---

# TASK-004: FollowUpCareAgent Extension — Care Pathway Activation & HIGH-Risk Pub/Sub Alert

> **Story:** US-040 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039/TASK-004 implemented `FollowUpCareAgent.process()` up to the point of persisting `encounter.risk_score` and `encounter.risk_tier`. US-040 extends `process()` with two additional steps that occur immediately after risk score persistence:

1. **Care pathway activation** — calls `CarePathwayService.activate_pathway()` (TASK-003) to create the `appointment` record for all three risk tiers.
2. **HIGH-risk care manager alert** — if `risk_tier=HIGH`, publishes a `CARE_MANAGER_ALERT` message to the `notification-requests` Pub/Sub topic with payload: `encounter_id`, `risk_score`, `risk_tier=HIGH`, `required_followup_days=7`. This must complete within 60 seconds of the A03 event (AC Scenario 1).

The entire `process()` method runs within a single database transaction — the `appointment` DB write and Pub/Sub publish are orchestrated as a unit (publish-after-commit pattern to avoid sending alerts for rolled-back appointments).

**Design references:**
- design.md §3.2 — Agent container pattern: Pub/Sub subscription, Pydantic output, DB write, SignalR push
- design.md §7.5 AIR-040 — `notification-requests` Pub/Sub topic; idempotency key prevents duplicate sends
- design.md §9.2 — `followup-agent` Cloud Run: min=1, max=10, 1 vCPU, 1 GB, Concurrency=20
- US-040 AC Scenario 1 — `CARE_MANAGER_ALERT` published to `notification-requests` within 60 s of A03
- US-040 AC Scenario 1 — alert payload: `encounter_id`, `risk_score`, `risk_tier=HIGH`, `required_followup_days=7`
- US-040 AC Scenario 4 — LOW tier: no `CARE_MANAGER_ALERT` published
- ADR-001 — Pub/Sub: dedicated `followup-agent-sub` subscription; publish to `notification-requests` topic

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `CARE_MANAGER_ALERT` published to `notification-requests` within 60 s of A03 for HIGH-risk patient |
| Scenario 2 | `appointment` record persisted via `CarePathwayService` for HIGH tier |
| Scenario 3 | `appointment` record persisted via `CarePathwayService` for MEDIUM tier; no alert |
| Scenario 4 | `appointment` record persisted via `CarePathwayService` for LOW tier; no alert |

---

## Implementation Steps

### 1. Add `CareManagerAlertPayload` to `backend/app/agents/followup_care/schemas.py`

Extend the existing schemas file from US-039/TASK-004:

```python
# Append to backend/app/agents/followup_care/schemas.py

class CareManagerAlertPayload(BaseModel):
    """Pub/Sub message payload for CARE_MANAGER_ALERT notifications.

    Published to the `notification-requests` topic when a HIGH-risk patient
    is discharged. Consumed by the Notification Service (AIR-040).

    Fields match US-040 AC Scenario 1 payload specification exactly.
    """

    alert_type: str = Field(default="CARE_MANAGER_ALERT", description="Notification type discriminator")
    encounter_id: str = Field(..., description="UUID of the high-risk encounter")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Predicted 30-day readmission probability")
    risk_tier: str = Field(default="HIGH", description="Risk tier — always HIGH for this alert type")
    required_followup_days: int = Field(..., description="Days within which follow-up must occur (=7 for HIGH)")
    appointment_id: str = Field(..., description="UUID of the created appointment record")
    idempotency_key: str = Field(
        ...,
        description="Unique key to prevent duplicate alert sends (AIR-040). "
        "Format: CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}",
    )
```

### 2. Add `NotificationPublisher` to `backend/app/agents/followup_care/notification_publisher.py`

```python
"""Pub/Sub publisher for care manager alert notifications.

Publishes `CARE_MANAGER_ALERT` messages to the `notification-requests` Pub/Sub topic
after an appointment is created for a HIGH-risk patient.

Publish pattern: publish-after-commit — the Pub/Sub message is published only after
the DB transaction commits to avoid sending alerts for rolled-back appointments.

Idempotency: the `idempotency_key` field in the payload prevents the Notification
Service from sending duplicate SMS/email if this message is redelivered (AIR-040).

Design refs:
    design.md §7.5 AIR-040 — notification-requests topic; idempotency key
    US-040 AC Scenario 1 — CARE_MANAGER_ALERT payload specification
    ADR-001 — Pub/Sub topic per logical channel (notification-requests)
"""
from __future__ import annotations

import json
import logging

from google.cloud import pubsub_v1

from app.agents.followup_care.schemas import CareManagerAlertPayload

logger = logging.getLogger(__name__)


class NotificationPublisher:
    """Thin wrapper around google-cloud-pubsub for alert dispatch.

    Args:
        project_id:          GCP project ID (from environment / Secret Manager).
        topic_id:            Pub/Sub topic name (default: notification-requests).
        publisher_client:    Optional pre-built PublisherClient for testing injection.
    """

    def __init__(
        self,
        project_id: str,
        topic_id: str = "notification-requests",
        publisher_client: pubsub_v1.PublisherClient | None = None,
    ) -> None:
        self._topic_path = f"projects/{project_id}/topics/{topic_id}"
        self._client = publisher_client or pubsub_v1.PublisherClient()

    def publish_care_manager_alert(self, payload: CareManagerAlertPayload) -> str:
        """Publish a CARE_MANAGER_ALERT to the notification-requests topic.

        Args:
            payload: Validated CareManagerAlertPayload Pydantic model.

        Returns:
            Pub/Sub message ID (string) returned by the broker.

        Raises:
            google.api_core.exceptions.GoogleAPIError: On Pub/Sub publish failure.
                Caller (FollowUpCareAgent.process) is responsible for retry/nack.
        """
        data = payload.model_dump_json().encode("utf-8")
        future = self._client.publish(
            self._topic_path,
            data=data,
            idempotency_key=payload.idempotency_key,
        )
        message_id: str = future.result(timeout=10)

        logger.info(
            "CARE_MANAGER_ALERT published",
            extra={
                "encounter_id": payload.encounter_id,
                "risk_tier": payload.risk_tier,
                "appointment_id": payload.appointment_id,
                "pubsub_message_id": message_id,
            },
        )
        return message_id
```

### 3. Extend `backend/app/agents/followup_care/agent.py`

Extend `FollowUpCareAgent.process()` — add care pathway activation and conditional alert dispatch after the existing risk score persistence block from US-039/TASK-004:

```python
# In FollowUpCareAgent.process(), after the existing risk score persistence block:

# ── Step 5: Activate care pathway (US-040) ─────────────────────────────────────
discharge_date = encounter.discharge_date.date()  # discharge_date is a datetime column

appointment = await self._care_pathway_service.activate_pathway(
    encounter=encounter,
    risk_tier=risk_result.risk_tier.value,
    discharge_date=discharge_date,
    db=db,
)

# Commit both the risk score update and the appointment in a single transaction
await db.commit()

# ── Step 6: Publish CARE_MANAGER_ALERT for HIGH-risk tier (US-040) ────────────
# Publish AFTER commit — avoids sending alerts for rolled-back appointments.
if risk_result.risk_tier.value == "HIGH":
    pathway_config = self._care_pathway_config["HIGH"]
    alert_payload = CareManagerAlertPayload(
        encounter_id=str(encounter.id),
        risk_score=risk_result.risk_score,
        risk_tier="HIGH",
        required_followup_days=pathway_config.required_followup_days,
        appointment_id=str(appointment.id),
        idempotency_key=f"CARE_MANAGER_ALERT:{encounter.id}:{appointment.id}",
    )
    self._notification_publisher.publish_care_manager_alert(alert_payload)
```

### 4. Update `FollowUpCareAgent.__init__` to accept new dependencies

```python
# In backend/app/agents/followup_care/agent.py — extend __init__:

def __init__(
    self,
    db_session_factory: AsyncSessionFactory,
    inference_client: InferenceClient,
    fhir_client: FHIRClient,
    care_pathway_service: CarePathwayService,        # NEW — US-040/TASK-003
    notification_publisher: NotificationPublisher,    # NEW — US-040/TASK-004
    care_pathway_config: CarePathwayConfig,           # NEW — US-040/TASK-002
) -> None:
    self._db_session_factory = db_session_factory
    self._inference_client = inference_client
    self._fhir_client = fhir_client
    self._care_pathway_service = care_pathway_service
    self._notification_publisher = notification_publisher
    self._care_pathway_config = care_pathway_config
```

### 5. Update `backend/app/agents/followup_care/main.py` — wire new dependencies

```python
# In main.py lifespan startup block — add after existing service instantiation:

from app.config.care_pathways import load_care_pathways
from app.services.care_pathway_service import CarePathwayService
from app.agents.followup_care.notification_publisher import NotificationPublisher

care_pathway_config = load_care_pathways()
care_pathway_service = CarePathwayService(pathways=care_pathway_config)
notification_publisher = NotificationPublisher(
    project_id=settings.GCP_PROJECT_ID,
    topic_id=settings.NOTIFICATION_REQUESTS_TOPIC,
)

agent = FollowUpCareAgent(
    db_session_factory=db_session_factory,
    inference_client=inference_client,
    fhir_client=fhir_client,
    care_pathway_service=care_pathway_service,        # NEW
    notification_publisher=notification_publisher,    # NEW
    care_pathway_config=care_pathway_config,          # NEW
)
```

### 6. Add `NOTIFICATION_REQUESTS_TOPIC` to settings

```python
# In backend/app/core/config.py — add to Settings model:
NOTIFICATION_REQUESTS_TOPIC: str = "notification-requests"
```

---

## Validation Checklist

- [ ] `CareManagerAlertPayload` Pydantic schema defined in `schemas.py` with all required fields
- [ ] `NotificationPublisher.publish_care_manager_alert()` publishes to `notification-requests` topic with `idempotency_key` attribute
- [ ] `FollowUpCareAgent.process()` calls `CarePathwayService.activate_pathway()` for all risk tiers
- [ ] `db.commit()` includes both `encounter` risk score update AND `appointment` insert (single transaction)
- [ ] Pub/Sub publish happens **after** `db.commit()` — no alert sent for rolled-back DB state
- [ ] `CARE_MANAGER_ALERT` published only when `risk_tier == "HIGH"` (not MEDIUM or LOW)
- [ ] Alert payload contains exactly: `encounter_id`, `risk_score`, `risk_tier=HIGH`, `required_followup_days=7`, `appointment_id`, `idempotency_key`
- [ ] `idempotency_key` format: `CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}`
- [ ] Logs include only UUIDs and numeric values — no PHI (AIR-021, BR-021)

---

## DoD Exit Criteria

- [ ] `backend/app/agents/followup_care/notification_publisher.py` created with `NotificationPublisher`
- [ ] `CareManagerAlertPayload` added to `schemas.py`
- [ ] `FollowUpCareAgent.process()` extended: care pathway activation + alert dispatch for HIGH tier
- [ ] Single DB transaction covers both risk score update and appointment creation
- [ ] Pub/Sub publish-after-commit pattern implemented correctly
- [ ] `FollowUpCareAgent.__init__` updated with `care_pathway_service`, `notification_publisher`, `care_pathway_config`
- [ ] `main.py` wires all new dependencies at startup
