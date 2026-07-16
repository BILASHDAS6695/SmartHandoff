---
id: TASK-004
title: "Implement `EscalationPublisher` — Pub/Sub Escalation with Idempotency Guard"
user_story: US-021
epic: EP-003
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, US-020/TASK-001]
---

# TASK-004: Implement `EscalationPublisher` — Pub/Sub Escalation with Idempotency Guard

> **Story:** US-021 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-021 Scenario 1 specifies the exact Pub/Sub payload and US-021 Technical Notes mandate idempotency:

> *"Escalation idempotency: only fire one escalation per (encounter_id, agent_type, breach_window) to avoid alert fatigue"*
> *"Escalation published to Pub/Sub `notification-requests` topic with structured payload"*

Payload shape (Scenario 1):

```json
{
  "notification_type": "SUPERVISOR_ESCALATION",
  "encounter_id": "<uuid>",
  "agent_type": "DOCUMENTATION",
  "minutes_elapsed": 30,
  "supervisor_id": "<uuid>",
  "fired_at": "<ISO-8601 UTC>"
}
```

Idempotency strategy: An in-process `set` tracks `(encounter_id, agent_type, breach_window_key)` keys already published during the current service lifetime. The `breach_window_key` is derived from the `SLAConfig.escalation_dedup_window_minutes` setting so that the dedup window matches the configured threshold. This avoids database round-trips for idempotency checks.

For production-grade cross-instance deduplication, a Cloud Memorystore (Redis) key with TTL equal to `escalation_dedup_window_minutes` would be used — flagged as a Phase 2 improvement in this task.

---

## Acceptance Criteria Addressed

| US-021 AC | Requirement |
|---|---|
| **Scenario 1** | `SUPERVISOR_ESCALATION` published to `notification-requests` Pub/Sub topic with all required fields |
| **DoD** | Escalation idempotency: one escalation per (encounter_id, agent_type, breach_window) |

---

## Implementation Steps

### 1. Create `sla-monitor/app/publisher/escalation_publisher.py`

```python
"""EscalationPublisher — publishes SUPERVISOR_ESCALATION messages to Pub/Sub.

Implements idempotency per US-021 Technical Notes:
  - Only one escalation fires per (encounter_id, agent_type, breach_window_key).
  - Dedup window derived from SLAConfig.escalation_dedup_window_minutes.
  - In-process set used for single-instance deduplication.
  - Phase 2: replace with Redis TTL key for multi-instance deduplication.

Pub/Sub topic: `notification-requests` (US-021 Scenario 1).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from google.cloud import pubsub_v1

from app.config.sla_loader import load_sla_config

logger = logging.getLogger(__name__)


class EscalationPublisher:
    """Publishes SUPERVISOR_ESCALATION Pub/Sub messages with idempotency guard.

    Args:
        project_id: GCP project ID.
        topic_id: Pub/Sub topic name (default: ``notification-requests``).
    """

    def __init__(
        self,
        project_id: str,
        topic_id: str = "notification-requests",
    ) -> None:
        self._topic_path = pubsub_v1.PublisherClient.topic_path(project_id, topic_id)
        self._publisher = pubsub_v1.PublisherClient()
        self._config = load_sla_config()
        # In-process idempotency set: (encounter_id_str, agent_type, window_bucket)
        # Phase 2: Replace with Redis SETNX TTL for cross-instance dedup.
        self._published_keys: set[tuple[str, str, int]] = set()

    def _breach_window_bucket(self, fired_at: datetime) -> int:
        """Derive a time bucket for dedup window partitioning.

        Tasks are bucketed into windows of `escalation_dedup_window_minutes`.
        Two calls within the same window for the same task map to the same bucket.

        Example: dedup_window=30, fired_at=10:47 → bucket = 10:47 // 30 = 21
        """
        total_minutes_since_epoch = int(fired_at.timestamp() / 60)
        return total_minutes_since_epoch // self._config.escalation_dedup_window_minutes

    async def publish(
        self,
        encounter_id: UUID,
        agent_type: str,
        minutes_elapsed: int,
        supervisor_id: UUID | None,
    ) -> None:
        """Publish a SUPERVISOR_ESCALATION message to the notification-requests topic.

        Skips publishing if an identical escalation was already fired within the
        current dedup window (in-process idempotency).

        Args:
            encounter_id: Encounter UUID being escalated.
            agent_type: Agent type whose SLA was breached.
            minutes_elapsed: Minutes since task creation at time of breach.
            supervisor_id: Supervisor to notify (may be None if unresolved).
        """
        fired_at = datetime.now(tz=timezone.utc)
        window_bucket = self._breach_window_bucket(fired_at)
        dedup_key = (str(encounter_id), agent_type, window_bucket)

        if dedup_key in self._published_keys:
            logger.debug(
                "Escalation suppressed (dedup): encounter_id=%s agent_type=%s window_bucket=%d",
                encounter_id,
                agent_type,
                window_bucket,
            )
            return

        payload = {
            "notification_type": "SUPERVISOR_ESCALATION",
            "encounter_id": str(encounter_id),
            "agent_type": agent_type,
            "minutes_elapsed": minutes_elapsed,
            "supervisor_id": str(supervisor_id) if supervisor_id else None,
            "fired_at": fired_at.isoformat(),
        }
        data = json.dumps(payload).encode("utf-8")

        try:
            future = self._publisher.publish(
                self._topic_path,
                data,
                notification_type="SUPERVISOR_ESCALATION",
                encounter_id=str(encounter_id),
                agent_type=agent_type,
            )
            message_id = future.result(timeout=10)
            self._published_keys.add(dedup_key)
            logger.info(
                "Escalation published: message_id=%s encounter_id=%s agent_type=%s "
                "minutes_elapsed=%d supervisor_id=%s",
                message_id,
                encounter_id,
                agent_type,
                minutes_elapsed,
                supervisor_id,
            )
        except Exception:
            logger.exception(
                "Failed to publish escalation: encounter_id=%s agent_type=%s",
                encounter_id,
                agent_type,
            )
            # Do NOT add to _published_keys on failure — allows retry on next tick.
            raise
```

### 2. Pub/Sub Topic Terraform Resource

Ensure the `notification-requests` topic exists. Add to the appropriate Terraform environment module:

```hcl
# infra/terraform/modules/pubsub/main.tf (or environment-specific override)
resource "google_pubsub_topic" "notification_requests" {
  name    = "notification-requests"
  project = var.project_id

  labels = {
    service     = "sla-monitor"
    environment = var.environment
  }
}

resource "google_pubsub_subscription" "notification_service_sub" {
  name    = "notification-service-sub"
  topic   = google_pubsub_topic.notification_requests.name
  project = var.project_id

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.notification_requests_dlq.name
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
}

resource "google_pubsub_topic" "notification_requests_dlq" {
  name    = "notification-requests-dlq"
  project = var.project_id
}
```

---

## Validation Checklist

- [ ] `publish()` sends message with all five fields: `notification_type`, `encounter_id`, `agent_type`, `minutes_elapsed`, `supervisor_id`, `fired_at`
- [ ] Duplicate call for same `(encounter_id, agent_type)` within the dedup window does NOT publish a second message
- [ ] Duplicate call after the dedup window expires DOES publish a new message
- [ ] Failed `future.result()` does NOT add to `_published_keys` — allows retry on next tick
- [ ] `notification-requests` Pub/Sub topic declared in Terraform with DLQ subscription
- [ ] Pub/Sub attributes include `notification_type`, `encounter_id`, `agent_type` for subscription filter routing

---

## Files Created / Modified

| Path | Change |
|---|---|
| `sla-monitor/app/publisher/escalation_publisher.py` | New — `EscalationPublisher` with idempotency guard |
| `infra/terraform/modules/pubsub/main.tf` | Add `notification-requests` topic + DLQ subscription |

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `google-cloud-pubsub` | Runtime | Pub/Sub client |
| TASK-001 | Task | `load_sla_config()` for dedup window config |
| US-020/TASK-001 | Story | Pub/Sub client pattern reference |
