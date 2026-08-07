"""Entry point for the ADT Ingest Cloud Run Job.

Invoked on a Cloud Scheduler cron trigger (recommended: every 1 minute).
Polls the configured FHIR server for recently updated Encounter resources,
detects ADT events, and broadcasts them via Azure SignalR Service.

Design refs:
    US-022 / US-048 — Real-time dashboard ADT events
    ADR-002         — Cloud Run stateless jobs for batch processing
"""
from __future__ import annotations

import asyncio
import logging
import sys

from app.core.config import get_settings
from app.signalr.adt_ingest import AdtIngestService
from app.signalr.broadcaster import SignalRBroadcaster

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run one ADT ingest poll/broadcast cycle."""
    settings = get_settings()
    connection_string = settings.AZURE_SIGNALR_CONNECTION_STRING
    if not connection_string:
        logger.error("AZURE_SIGNALR_CONNECTION_STRING is not configured; aborting ADT ingest job")
        sys.exit(1)

    broadcaster = SignalRBroadcaster(connection_string)
    service = AdtIngestService(broadcaster)

    try:
        result = await service.poll_and_broadcast()
        logger.info("ADT ingest job finished: %s", result)
    finally:
        await service.close()
        await broadcaster.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except Exception as exc:
        logger.exception("ADT ingest job failed: %s", exc)
        sys.exit(1)
