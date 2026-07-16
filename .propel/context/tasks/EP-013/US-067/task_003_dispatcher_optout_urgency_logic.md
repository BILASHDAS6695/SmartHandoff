---
id: TASK-003
title: "Implement Opt-Out Suppression + Urgency Bypass in `notification-service/app/dispatcher.py`"
user_story: US-067
epic: EP-013
sprint: 2
layer: Backend / Business Logic
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, US-064]
---

# TASK-003: Implement Opt-Out Suppression + Urgency Bypass in `notification-service/app/dispatcher.py`

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Business Logic | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-067 DoD specifies:

> *"Opt-out check in notification service: `if patient.notification_opt_out and not msg.urgency_override: skip()`"*
> *"Audit log entry created for every notification delivery attempt (BR-012 compliance)"*

The `NotificationService` dispatcher (established in US-064) receives `NotificationMessage` payloads from Pub/Sub and dispatches via Twilio (SMS) or SendGrid (Email). US-067 adds a pre-dispatch gate:

1. **Load patient opt-out preference** from `patient.notification_opt_out` (read from DB)
2. **If opted out AND not urgency override** → set `delivery_status=OPTED_OUT`, persist `notification` record, skip dispatch
3. **If urgent override** → proceed with dispatch regardless of opt-out; persist `urgency_override=True` on `notification` record
4. **Every attempt** (including opt-out skips) → create audit log entry (BR-012)

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Opt-out check placed before dispatch, after idempotency check | Prevents sending then recording OPTED_OUT; also prevents double-inserting if duplicate key received |
| Patient lookup uses `recipient_id` from Pub/Sub message | `recipient_id` is the `patient.id` UUID; single DB read per message is acceptable (non-PHI field, not encrypted) |
| `notification` record created even for OPTED_OUT | AC Scenario 2 requires a record with `delivery_status=OPTED_OUT`; audit completeness per BR-012 |
| `urgency_override` written to `notification` record | AC Scenario 3 requires `urgency_override=True` on the persisted record for audit evidence |
| Audit log entry via existing `audit_log` mechanism | BR-012 compliance; reuses the same audit log infrastructure as all other services (design.md §8) |
| Patient read from **write primary** (not read replica) | Opt-out is a safety-critical preference; stale replica data could cause accidental send to opted-out patient |

Design refs: US-064 dispatcher (Twilio/SendGrid dispatch), TASK-001 (ORM changes), TASK-002 (Pub/Sub schema), design.md §3.1, ADR-007.

---

## Acceptance Criteria Addressed

| US-067 AC | Requirement |
|---|---|
| **Scenario 2** | `medication_reminder` for opted-out patient → `delivery_status=OPTED_OUT`; no SMS/email dispatched |
| **Scenario 3** | `CARE_TEAM_URGENCY_ALERT` with `urgency_override=True` → sent despite opt-out; `delivery_status=SENT`, `urgency_override=True` on record |
| **DoD** | Opt-out check: `if patient.notification_opt_out and not msg.urgency_override: skip()` |
| **DoD** | Audit log entry for every notification delivery attempt (BR-012) |

---

## Implementation Steps

### 1. Locate the existing dispatcher

The dispatcher is at `notification-service/app/dispatcher.py` (created by US-064 TASK-003/004). The following changes are surgical additions to the existing dispatch flow.

### 2. Add `_get_patient_opt_out` helper

```python
# notification-service/app/dispatcher.py
# Add after existing imports

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.patient import Patient  # patient ORM is in backend; use shared DB session or remote call
from app.models.notification import DeliveryStatus


async def _get_patient_opt_out(
    patient_id: UUID,
    db: AsyncSession,
) -> bool:
    """Fetch patient.notification_opt_out from the write primary.

    Uses write primary (not read replica) to prevent stale opt-out data
    causing accidental dispatch to an opted-out patient.

    Args:
        patient_id: The patient UUID from the Pub/Sub message recipient_id.
        db: Write-primary AsyncSession.

    Returns:
        True if the patient has opted out of non-urgent notifications.
        False if the patient is opted in or not found (fail-open for safety).
    """
    result = await db.execute(
        select(Patient.notification_opt_out).where(Patient.id == patient_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # Patient not found — log warning; fail-open (do not suppress)
        logger.warning(
            "opt_out_check_patient_not_found",
            patient_id=str(patient_id),
        )
        return False
    return bool(row)
```

### 3. Integrate opt-out gate into the dispatch flow

Add the opt-out check immediately after the idempotency check and before the Twilio/SendGrid dispatch call:

```python
async def dispatch_notification(
    msg: NotificationMessage,
    db: AsyncSession,
) -> None:
    """Dispatch a notification with opt-out suppression and urgency bypass.

    Flow:
        1. Idempotency check (US-064)
        2. Opt-out check (US-067)
        3. Dispatch via Twilio/SendGrid (US-064)
        4. Audit log entry (BR-012, US-067)
    """
    # --- Step 1: Idempotency (existing US-064 logic) ---
    # ... existing idempotency check code ...

    # --- Step 2: Opt-out check (US-067) ---
    patient_opted_out = await _get_patient_opt_out(msg.recipient_id, db)

    if patient_opted_out and not msg.urgency_override:
        # Create OPTED_OUT notification record; do NOT dispatch
        notification = Notification(
            idempotency_key=msg.idempotency_key,
            type=msg.channel,
            delivery_status=DeliveryStatus.OPTED_OUT,
            recipient_id=msg.recipient_id,
            encounter_id=msg.encounter_id,
            template_name=msg.template_name,
            urgency_override=False,
            # recipient_phone_hash / recipient_email_hash: set to None (no dispatch attempt)
        )
        db.add(notification)
        await db.commit()

        await _write_audit_log(
            action="NOTIFICATION_SUPPRESSED_OPT_OUT",
            patient_id=msg.recipient_id,
            encounter_id=msg.encounter_id,
            notification_type=msg.notification_type,
            channel=msg.channel,
            db=db,
        )
        logger.info(
            "notification_suppressed_opt_out",
            idempotency_key=msg.idempotency_key,
            notification_type=msg.notification_type,
        )
        return  # Exit early — no dispatch

    # --- Step 3: Dispatch (existing US-064 logic, with urgency_override persisted) ---
    # ... existing Twilio/SendGrid dispatch code ...

    # When creating the notification record after successful dispatch, include:
    #   urgency_override=msg.urgency_override
    #   delivery_status=DeliveryStatus.SENT

    # --- Step 4: Audit log entry (BR-012) ---
    await _write_audit_log(
        action="NOTIFICATION_DISPATCHED",
        patient_id=msg.recipient_id,
        encounter_id=msg.encounter_id,
        notification_type=msg.notification_type,
        channel=msg.channel,
        urgency_override=msg.urgency_override,
        db=db,
    )
```

### 4. Implement `_write_audit_log` helper

```python
async def _write_audit_log(
    action: str,
    patient_id: UUID,
    encounter_id: UUID | None,
    notification_type: str,
    channel: str,
    urgency_override: bool = False,
    db: AsyncSession = None,
) -> None:
    """Write a structured audit log entry for BR-012 compliance.

    All notification delivery attempts (dispatched, suppressed, failed)
    must produce an audit log entry. PHI is never included in log payload.

    Args:
        action: 'NOTIFICATION_DISPATCHED' | 'NOTIFICATION_SUPPRESSED_OPT_OUT' | 'NOTIFICATION_FAILED'
        patient_id: Patient UUID (non-PHI identifier).
        encounter_id: Encounter UUID (non-PHI identifier).
        notification_type: Notification type string.
        channel: SMS or EMAIL.
        urgency_override: Whether urgency override was active.
        db: AsyncSession for writing to audit_log table.
    """
    from app.models.audit_log import AuditLog  # existing audit model

    entry = AuditLog(
        action=action,
        resource_type="notification",
        resource_id=None,
        patient_id=patient_id,
        encounter_id=encounter_id,
        metadata={
            "notification_type": notification_type,
            "channel": channel,
            "urgency_override": urgency_override,
        },
    )
    db.add(entry)
    await db.commit()
```

---

## Validation

```bash
cd notification-service

# Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/dispatcher.py').read_text())
print('Syntax check: PASSED')
"

# Integration smoke test (against local DB with test patient)
python -c "
import asyncio
from app.schemas.notification_message import NotificationMessage, NotificationChannel

# Simulate opted-out patient message (non-urgent)
msg_non_urgent = NotificationMessage.model_validate({
    'idempotency_key': 'test-optout-001',
    'type': 'medication_reminder',
    'channel': 'SMS',
    'recipient_id': '\$TEST_OPTED_OUT_PATIENT_ID',
    'template_name': 'medication_reminder',
    'urgency_override': False,
})
print('Non-urgent opted-out message parsed: PASSED')

# Simulate urgent override message
msg_urgent = NotificationMessage.model_validate({
    'idempotency_key': 'test-urgent-001',
    'type': 'CARE_TEAM_URGENCY_ALERT',
    'channel': 'SMS',
    'recipient_id': '\$TEST_OPTED_OUT_PATIENT_ID',
    'template_name': 'care_team_escalation',
    'urgency_override': True,
})
assert msg_urgent.urgency_override is True
print('Urgent override message parsed: PASSED')
"
```

---

## Files Involved

| File | Action | Notes |
|------|--------|-------|
| `notification-service/app/dispatcher.py` | Modify | Add opt-out gate with urgency bypass; persist `urgency_override` on `notification` record; add audit log on all attempts |
| `notification-service/app/models/notification.py` | Reference | `DeliveryStatus.OPTED_OUT` used in OPTED_OUT branch |

---

## Definition of Done (Task-Level)

- [ ] `_get_patient_opt_out` helper reads `patient.notification_opt_out` from write primary
- [ ] Opt-out gate: if `patient.notification_opt_out and not msg.urgency_override` → create `OPTED_OUT` notification record, skip dispatch
- [ ] Urgency bypass: `urgency_override=True` messages dispatched regardless of opt-out preference
- [ ] `urgency_override` persisted on `notification` record for both dispatched and skipped scenarios
- [ ] Audit log entry created for every attempt (BR-012): `NOTIFICATION_DISPATCHED`, `NOTIFICATION_SUPPRESSED_OPT_OUT`, `NOTIFICATION_FAILED`
- [ ] No PHI in log payloads (`patient_id` UUID only, no name/phone/email)
- [ ] Syntax check passes
- [ ] No regressions in existing US-064 dispatcher tests
