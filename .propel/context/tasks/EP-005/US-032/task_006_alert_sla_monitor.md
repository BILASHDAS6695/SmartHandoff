---
id: TASK-006
title: "AlertSLAMonitor — 24-Hour SLA Breach Detection and Charge Pharmacist Escalation"
user_story: US-032
epic: EP-005
sprint: 2
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-032/TASK-003, US-032/TASK-004]
---

# TASK-006: AlertSLAMonitor — 24-Hour SLA Breach Detection and Charge Pharmacist Escalation

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-032 AC Scenario 3 requires a SLA monitor that detects `HIGH`-severity pharmacist alerts that have been unresolved for ≥ 24 hours and:

1. Tags the alert `sla_breached = True`.
2. Publishes a `CHARGE_PHARMACIST_ESCALATION` notification to the `notification-requests` Pub/Sub topic.

The monitor runs as a scheduled Cloud Run Job (or background task) and is idempotent — re-running it on an already-breached alert must not re-publish the escalation notification.

**Design references:**
- US-032 AC Scenario 3 — 24h SLA; `CHARGE_PHARMACIST_ESCALATION`; `sla_breached=True`
- design.md §3.1 — Medication Reconciliation Agent; Cloud Run
- ADR-001 — all events published to GCP Pub/Sub before side-effects
- TR-005 — async Pub/Sub publish confirmed before DB commit

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 3** | `CHARGE_PHARMACIST_ESCALATION` notification published; `sla_breached=True` tagged |

---

## Implementation Steps

### 1. Create `backend/app/services/alert_sla_monitor.py`

```python
"""AlertSLAMonitor — detects unresolved HIGH-severity alerts past the 24-hour SLA.

For each alert meeting the breach criteria, the monitor:
  1. Sets sla_breached = True on the PharmacistAlert record.
  2. Publishes a CHARGE_PHARMACIST_ESCALATION event to the notification-requests topic.

The monitor is idempotent: alerts already tagged sla_breached=True are skipped.

Design refs:
    US-032 AC Scenario 3   — 24h SLA; CHARGE_PHARMACIST_ESCALATION
    ADR-001                — publish to Pub/Sub before side-effects
    design.md §3.1         — Medication Reconciliation Agent; Cloud Run
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Final

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pubsub.publisher import publish_message
from app.models.pharmacist_alert import PharmacistAlert

logger = logging.getLogger(__name__)

SLA_THRESHOLD_HOURS: Final[int] = 24
_ESCALATION_TOPIC: Final[str] = "notification-requests"


class AlertSLAMonitor:
    """Scans active HIGH-severity alerts and escalates those past the SLA threshold.

    Args:
        db: Async SQLAlchemy session.
        sla_hours: SLA threshold in hours. Defaults to 24.
    """

    def __init__(
        self,
        db: AsyncSession,
        sla_hours: int = SLA_THRESHOLD_HOURS,
    ) -> None:
        self._db = db
        self._threshold = timedelta(hours=sla_hours)

    async def run(self) -> dict[str, int]:
        """Execute the SLA monitor cycle.

        Returns:
            Dict with ``checked``, ``breached``, and ``skipped`` counters.
        """
        cutoff: datetime = datetime.now(timezone.utc) - self._threshold

        stmt = select(PharmacistAlert).where(
            and_(
                PharmacistAlert.severity == "HIGH",
                PharmacistAlert.status == "ACTIVE",
                PharmacistAlert.sla_breached.is_(False),
                PharmacistAlert.created_at <= cutoff,
            )
        )
        result = await self._db.execute(stmt)
        candidates: list[PharmacistAlert] = list(result.scalars().all())

        logger.info("SLA monitor: found %d candidate alert(s) for breach check", len(candidates))

        checked = 0
        breached = 0
        skipped = 0

        for alert in candidates:
            checked += 1
            try:
                await self._escalate(alert)
                breached += 1
            except Exception:
                logger.exception(
                    "SLA escalation failed for alert_id=%s — skipping", alert.id
                )
                skipped += 1

        await self._db.flush()
        logger.info(
            "SLA monitor complete: checked=%d breached=%d skipped=%d",
            checked,
            breached,
            skipped,
        )
        return {"checked": checked, "breached": breached, "skipped": skipped}

    async def _escalate(self, alert: PharmacistAlert) -> None:
        """Tag the alert as SLA-breached and publish an escalation notification.

        Steps are ordered per ADR-001: publish to Pub/Sub first, then mutate DB.

        Args:
            alert: The :class:`PharmacistAlert` that has breached the SLA.
        """
        await publish_message(
            topic=_ESCALATION_TOPIC,
            data={
                "event_type": "CHARGE_PHARMACIST_ESCALATION",
                "alert_id": str(alert.id),
                "alert_type": alert.alert_type,
                "encounter_id": str(alert.encounter_id),
                "drug_class": alert.drug_class,
                "drug_name": alert.drug_name,
                "severity": alert.severity,
                "created_at": alert.created_at.isoformat(),
                "sla_threshold_hours": SLA_THRESHOLD_HOURS,
            },
            attributes={"priority": "IMMEDIATE"},
        )

        alert.sla_breached = True
        self._db.add(alert)
        logger.warning(
            "SLA breach escalated: alert_id=%s encounter_id=%s drug_class=%s",
            alert.id,
            alert.encounter_id,
            alert.drug_class,
        )
```

### 2. Create Cloud Run Job entry point `backend/app/jobs/run_sla_monitor.py`

```python
"""Entry point for the Alert SLA Monitor Cloud Run Job.

Invoked on a Cloud Scheduler cron trigger (every 30 minutes).

Design refs:
    US-032 AC Scenario 3 — 24h SLA threshold
    ADR-002              — Cloud Run stateless job
"""
from __future__ import annotations

import asyncio
import logging
import sys

from app.db.session import get_db_session_context
from app.services.alert_sla_monitor import AlertSLAMonitor

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the SLA monitor and exit with code 0 on success, 1 on failure."""
    async with get_db_session_context() as db:
        monitor = AlertSLAMonitor(db=db)
        results = await monitor.run()
        await db.commit()
    logger.info("SLA monitor job finished: %s", results)


if __name__ == "__main__":
    asyncio.run(main())
```

### 3. Register Cloud Run Job in Terraform

In `infra/terraform/modules/cloud_run/` (or the applicable environment `main.tf`), add a Cloud Run Job resource and a Cloud Scheduler job targeting it every 30 minutes:

```hcl
resource "google_cloud_run_v2_job" "alert_sla_monitor" {
  name     = "alert-sla-monitor-${var.environment}"
  location = var.region

  template {
    template {
      containers {
        image = var.medication_reconciliation_image

        command = ["python", "-m", "app.jobs.run_sla_monitor"]

        env {
          name  = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.db_url.secret_id
              version = "latest"
            }
          }
        }
      }
      service_account = google_service_account.medication_reconciliation_agent.email
    }
  }
}

resource "google_cloud_scheduler_job" "alert_sla_monitor_trigger" {
  name      = "alert-sla-monitor-trigger-${var.environment}"
  region    = var.region
  schedule  = "*/30 * * * *"
  time_zone = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.alert_sla_monitor.name}:run"

    oauth_token {
      service_account_email = google_service_account.medication_reconciliation_agent.email
    }
  }
}
```

---

## Validation

- [ ] `AlertSLAMonitor.run()` returns `{"checked": N, "breached": N, "skipped": 0}` when N alerts are ≥ 24h old and `status=ACTIVE`
- [ ] After `run()`, each breached alert has `sla_breached=True` in the database
- [ ] Re-running `run()` on already-breached alerts returns `{"checked": 0, "breached": 0, "skipped": 0}` (idempotent)
- [ ] Pub/Sub message `event_type=CHARGE_PHARMACIST_ESCALATION` published for each breached alert with `priority=IMMEDIATE`
- [ ] Alerts with `status=RESOLVED` are excluded from breach detection
- [ ] Alerts with `severity=MEDIUM` or `LOW` are excluded from breach detection
- [ ] Cloud Scheduler cron `*/30 * * * *` triggers Cloud Run Job every 30 minutes

---

## Files Changed

| Action | Path |
|--------|------|
| Create | `backend/app/services/alert_sla_monitor.py` |
| Create | `backend/app/jobs/run_sla_monitor.py` |
| Modify | `infra/terraform/modules/cloud_run/main.tf` (Cloud Run Job + Scheduler) |
