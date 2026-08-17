"""Entry point for the Scheduled Notification Dispatcher Cloud Run Job.

Invoked on a Cloud Scheduler cron trigger (recommended: every 1 minute).
Polls `scheduled_notification` for PENDING rows that are due, resolves patient
phone/email, and publishes to the `notification-requests` Pub/Sub topic.

Design refs:
    US-041 / US-067 — scheduled patient notifications and opt-out
    ADR-002         — Cloud Run stateless jobs for batch processing
    TR-011          — Cloud Scheduler cron triggers
"""
from __future__ import annotations

import asyncio
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import get_write_session
from app.services.patient_notification_publisher import PatientNotificationPublisher
from app.services.scheduled_notification_dispatcher import ScheduledNotificationDispatcher

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run one scheduled-notification dispatch cycle."""
    # AsyncIOScheduler is required by the dispatcher interface but is not
    # started here; the Cloud Run Job executes a single cycle and exits.
    scheduler = AsyncIOScheduler()
    publisher = PatientNotificationPublisher()
    dispatcher = ScheduledNotificationDispatcher(
        session_factory=get_write_session,
        publisher=publisher,
        scheduler=scheduler,
    )

    try:
        await dispatcher.run()
        logger.info("Scheduled notification dispatch job finished")
    finally:
        # Ensure any pending scheduler state is cleaned up even though it
        # was never started.
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except Exception as exc:
        logger.exception("Scheduled notification dispatch job failed: %s", exc)
        sys.exit(1)
