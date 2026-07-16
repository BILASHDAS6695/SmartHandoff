---
id: TASK-002
title: "Extend Notification Pub/Sub Message Schema — Add `urgency_override` Boolean Field"
user_story: US-067
epic: EP-013
sprint: 2
layer: Backend / Messaging
estimate: 0.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, US-064]
---

# TASK-002: Extend Notification Pub/Sub Message Schema — Add `urgency_override` Boolean Field

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Messaging | **Est:** 0.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-067 DoD specifies:

> *"`urgency_override` boolean field on notification Pub/Sub message schema"*
> *"Urgency override flag must be set by the sending agent (not overrideable by patient)"*

The notification Pub/Sub message schema was established in US-064. The schema is a Pydantic model representing the JSON payload published to the `adt-events` topic (or a dedicated `notifications` topic) and consumed by the `NotificationService` Cloud Run service.

US-067 adds `urgency_override: bool` as a new field with default `False`. The `NotificationService` consumer reads this flag to decide whether to apply opt-out suppression. Setting this flag is the exclusive responsibility of the sending agent (Follow-up Care Agent, Transition Coordinator Agent) — the patient portal PATCH endpoint (`/api/v1/portal/preferences`) cannot set this field.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `urgency_override: bool = False` default | Backward compatible: existing Pub/Sub publishers that do not include the field will parse as non-urgent (opt-out suppression applies) |
| Field is read-only from patient perspective | Patient portal only modifies `patient.notification_opt_out`; the `urgency_override` field is agent-owned |
| Pydantic v2 `model_config = ConfigDict(frozen=True)` | Message schema is parsed from JSON — immutability prevents accidental mutation during processing |
| Co-located with US-064 notification schemas | `notification-service/app/schemas/notification_message.py` is the single source of truth for the Pub/Sub contract |

Design refs: US-064 TASK-002 (Pub/Sub consumer), design.md §3.1 (Notification Service), ADR-001 (Pub/Sub event bus).

---

## Acceptance Criteria Addressed

| US-067 AC | Requirement |
|---|---|
| **Scenario 3** | `urgency_override=True` present on Pub/Sub message triggers bypass of opt-out suppression |
| **Scenario 2** | `urgency_override=False` (default) causes opt-out suppression for opted-out patients |
| **DoD** | `urgency_override` boolean field exists on notification Pub/Sub message schema |

---

## Implementation Steps

### 1. Locate the existing Pub/Sub message schema

The schema is at `notification-service/app/schemas/notification_message.py` (created by US-064 TASK-002). If the file does not exist yet, create it with the full content below.

### 2. Update `notification-service/app/schemas/notification_message.py`

```python
"""Pydantic v2 schema for the Notification Pub/Sub message payload.

This schema represents the JSON structure published to the Pub/Sub
``notifications`` topic and consumed by the NotificationService dispatcher.

Design refs:
    US-064 DoD (idempotency_key, type, channel, template_name, recipient_id)
    US-067 DoD (urgency_override — agent-set only; bypasses patient opt-out)
    ADR-001 (Pub/Sub event bus)
    design.md §3.1 (Notification Service component)

Security note:
    ``urgency_override`` is set exclusively by sending agents (Transition
    Coordinator, Follow-up Care Agent). The patient portal endpoint
    ``PATCH /api/v1/portal/preferences`` does NOT expose this field.
"""
from __future__ import annotations

import enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationChannel(str, enum.Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


class NotificationMessage(BaseModel):
    """Pub/Sub message payload for a notification dispatch request.

    Publishers:
        - TransitionCoordinatorAgent
        - FollowUpCareAgent
        - PatientCommunicationAgent

    Consumer:
        - NotificationService (notification-service Cloud Run service)
    """

    model_config = ConfigDict(frozen=True)

    idempotency_key: str = Field(
        ...,
        description="Unique key; duplicate messages with same key are discarded (US-064 Scenario 2)",
    )
    notification_type: str = Field(
        ...,
        alias="type",
        description="Notification type e.g. 'medication_reminder', 'CARE_TEAM_URGENCY_ALERT'",
    )
    channel: NotificationChannel = Field(
        ...,
        description="Dispatch channel: SMS or EMAIL",
    )
    recipient_id: UUID = Field(
        ...,
        description="patient.id — used to look up opt-out preference and hashed recipient contact",
    )
    encounter_id: Optional[UUID] = Field(
        default=None,
        description="encounter.id — linked encounter for audit log query (US-067 Scenario 1)",
    )
    template_name: str = Field(
        ...,
        description="SendGrid Dynamic Template key (maps to config/sendgrid_templates.yaml)",
    )
    template_data: dict = Field(
        default_factory=dict,
        description="Pydantic-validated substitution payload (US-066 SendGrid schemas)",
    )
    urgency_override: bool = Field(
        default=False,
        description=(
            "When True, notification bypasses patient opt-out (US-067 Scenario 3). "
            "MUST be set only by authorised sending agents — never by patient-facing APIs."
        ),
    )

    model_config = ConfigDict(frozen=True, populate_by_name=True)
```

### 3. Verify backward compatibility

Existing Pub/Sub publishers that omit `urgency_override` will parse successfully because `default=False` is set. Run a quick parse check:

```python
# Quick backward-compat check
from notification_service.app.schemas.notification_message import NotificationMessage
import json

# Old message (without urgency_override) must parse without error
old_payload = {
    "idempotency_key": "test-001",
    "type": "medication_reminder",
    "channel": "SMS",
    "recipient_id": "00000000-0000-0000-0000-000000000001",
    "template_name": "medication_reminder",
}
msg = NotificationMessage.model_validate(old_payload)
assert msg.urgency_override is False, "Default must be False for backward compat"
print("Backward compat: PASSED")

# Urgent message with override
urgent_payload = {**old_payload, "type": "CARE_TEAM_URGENCY_ALERT", "urgency_override": True}
msg2 = NotificationMessage.model_validate(urgent_payload)
assert msg2.urgency_override is True
print("Urgency override: PASSED")
```

---

## Validation

```bash
cd notification-service

# Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/schemas/notification_message.py').read_text())
print('Syntax check: PASSED')
"

# Schema parse check
python -c "
from app.schemas.notification_message import NotificationMessage
msg = NotificationMessage.model_validate({
    'idempotency_key': 'k1',
    'type': 'medication_reminder',
    'channel': 'SMS',
    'recipient_id': '00000000-0000-0000-0000-000000000001',
    'template_name': 'medication_reminder',
})
assert msg.urgency_override is False
print('Default urgency_override=False: PASSED')

urgent = NotificationMessage.model_validate({
    'idempotency_key': 'k2',
    'type': 'CARE_TEAM_URGENCY_ALERT',
    'channel': 'SMS',
    'recipient_id': '00000000-0000-0000-0000-000000000001',
    'template_name': 'care_team_escalation',
    'urgency_override': True,
})
assert urgent.urgency_override is True
print('urgency_override=True: PASSED')
"
```

---

## Files Involved

| File | Action | Notes |
|------|--------|-------|
| `notification-service/app/schemas/notification_message.py` | Modify | Add `urgency_override: bool = False` field to `NotificationMessage` |
| `notification-service/app/schemas/__init__.py` | Modify | Ensure `NotificationMessage` is exported |

---

## Definition of Done (Task-Level)

- [ ] `urgency_override: bool = Field(default=False, ...)` added to `NotificationMessage`
- [ ] Existing message payloads without `urgency_override` parse without error (default=False)
- [ ] `urgency_override=True` parses correctly for urgent notifications
- [ ] Syntax check passes
- [ ] No regressions in existing US-064 consumer tests
