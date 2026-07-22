"""HL7 Listener service entry point (app package).

Starts two concurrent asyncio servers:
  1. MLLP TCP server on port 2575  — HL7 ADT ingestion (app/mllp/server.py)
  2. HTTP server on port 8080      — /health, /ready, /metrics (app/health.py)

Cloud Run configuration:
  - Set ``--port=2575`` for TCP traffic routing (or GKE TCP LoadBalancer).
  - Health probes target port 8080 via HTTP liveness/readiness paths.

Run with:
    python -m app.main

Design refs:
    AIR-001, AIR-004, TR-016, US-011
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the MLLP TCP server and HTTP health server concurrently.

    Startup sequence (US-013 / US-014):
      1. Construct FallbackQueue and GCSArchiver with circular reference.
      2. Start FallbackQueue background flush task.
      3. Construct PublishRetryQueue and ADTEventPublisher (US-014).
      4. Start PublishRetryQueue background flush task (US-014).
      5. Initialise the MLLP processing pipeline with all dependencies.
      6. Run MLLP + health servers concurrently.
      7. On shutdown, stop PublishRetryQueue, close publisher, stop FallbackQueue.
    """
    from app.health import start_health_server
    from app.mllp.server import start_mllp_server
    from app.archive.gcs_archiver import GCSArchiver
    from app.archive.fallback_queue import FallbackQueue
    from app.mllp.pipeline import init_pipeline
    from app.pubsub.adt_event_publisher import ADTEventPublisher
    from app.pubsub.publish_retry_queue import PublishRetryQueue

    host = os.getenv("MLLP_HOST", "0.0.0.0")
    mllp_port = int(os.getenv("MLLP_PORT", "2575"))
    health_port = int(os.getenv("HEALTH_PORT", "8080"))

    # -- US-013: Initialise GCS archive pipeline ----------------------------
    gcs_archiver: GCSArchiver = GCSArchiver(fallback_queue=None)
    fallback_queue: FallbackQueue = FallbackQueue(archiver=gcs_archiver)
    gcs_archiver._fallback_queue = fallback_queue  # complete circular ref

    await fallback_queue.start()

    # -- US-014: Initialise Pub/Sub publisher pipeline ----------------------
    # PublishRetryQueue needs a publish_fn reference; ADTEventPublisher needs
    # the retry_queue reference.  Resolve the circular dependency by
    # constructing both and completing the reference before starting.
    publish_retry_queue: PublishRetryQueue = PublishRetryQueue(
        publish_fn=lambda event: _noop_publish(event)
    )
    gcs_publisher: ADTEventPublisher = ADTEventPublisher(
        retry_queue=publish_retry_queue
    )
    # Patch publish_fn to the real publisher (breaks circular import at init)
    publish_retry_queue._publish_fn = gcs_publisher.publish

    await publish_retry_queue.start()

    init_pipeline(
        fallback_queue=fallback_queue,
        gcs_archiver=gcs_archiver,
        publisher=gcs_publisher,
        publish_retry_queue=publish_retry_queue,
    )

    logger.info(
        "hl7_listener_starting mllp_port=%d health_port=%d",
        mllp_port,
        health_port,
    )

    try:
        await asyncio.gather(
            start_mllp_server(host=host, port=mllp_port),
            start_health_server(host=host, port=health_port),
        )
    finally:
        # -- US-014: Graceful shutdown — drain Pub/Sub retry queue (TR-017) -
        await publish_retry_queue.stop()
        await gcs_publisher.close()
        # -- US-013: Graceful shutdown — drain GCS fallback queue (TR-017) --
        await fallback_queue.stop()


async def _noop_publish(event: object) -> None:  # type: ignore[type-arg]
    """Placeholder publish function used only during object construction."""
    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("hl7_listener_shutdown")
