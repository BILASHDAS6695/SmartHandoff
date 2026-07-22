"""MLLP message processing pipeline — extended with archive, idempotency, and Pub/Sub.

Processing order (US-011 → US-013 → US-014):
  1. Extract MSH-10 from raw bytes (no full parse needed yet)
  2. Archive raw HL7 to GCS via GCSArchiver [SC-1 — before ACK]
  3. Idempotency check via IdempotencyChecker [SC-2 — before Pub/Sub]
     └── Duplicate → return ACK (AA) immediately
  4. Parse HL7 to ADTEvent via HL7Parser
  5. Route ADTEvent to registered handler via ADTRouter
  6. Publish ADTEvent to Pub/Sub via ADTEventPublisher  [US-014]
  7. Return ACK (AA)  ← deferred until step 6 completes (US-014 SC-3)

Fail-open policy for idempotency DB failure:
  If the DB is unreachable, SQLAlchemyError is caught and logged.
  The pipeline continues (treat as non-duplicate) to avoid blocking
  all HL7 ingestion on a DB connectivity blip.  Cloud Monitoring P1
  alert for DB replication lag fires independently (TR-014).

Design refs:
    AIR-001 — MLLP ACK within 200 ms of receipt
    AIR-003 — archive before ACK (SC-1)
    ADR-001 — all ADT events published to Pub/Sub before agent processing
    DR-022  — MSH-10 idempotency (SC-2)
    TR-017  — graceful shutdown; GCSArchiver uses FallbackQueue on SIGTERM
    US-011  — MLLP server and ACK/NACK builders (upstream)
    US-012  — HL7Parser, ADTRouter, ADTEvent
    US-014  — ADTEventPublisher, PublishRetryQueue
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.archive.gcs_archiver import GCSArchiver
from app.archive.fallback_queue import FallbackQueue
from app.idempotency.idempotency_checker import IdempotencyChecker
from app.mllp.ack_builder import build_ack_response, build_nack_response
from app.parser.models import HL7ValidationError
from app.parser.hl7_parser import HL7Parser
from app.parser.router import default_router
from app.db.session import get_async_session
from app.pubsub.adt_event_publisher import ADTEventPublisher
from app.pubsub.publish_retry_queue import PublishRetryQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — initialised at service startup (see main.py)
# ---------------------------------------------------------------------------

_fallback_queue: FallbackQueue | None = None
_gcs_archiver: GCSArchiver | None = None
_idempotency_checker = IdempotencyChecker()
_hl7_parser = HL7Parser()
_publisher: ADTEventPublisher | None = None
_publish_retry_queue: PublishRetryQueue | None = None


def init_pipeline(
    fallback_queue: FallbackQueue,
    gcs_archiver: GCSArchiver,
    publisher: ADTEventPublisher | None = None,
    publish_retry_queue: PublishRetryQueue | None = None,
) -> None:
    """Initialise pipeline dependencies at service startup.

    Called from ``main.py`` after the asyncio event loop is running and
    ``FallbackQueue.start()`` has been awaited.

    Args:
        fallback_queue:      Started ``FallbackQueue`` instance.
        gcs_archiver:        ``GCSArchiver`` configured with ``fallback_queue``.
        publisher:           ``ADTEventPublisher`` for Pub/Sub dispatch (US-014).
        publish_retry_queue: ``PublishRetryQueue`` started instance (US-014).
    """
    global _fallback_queue, _gcs_archiver, _publisher, _publish_retry_queue
    _fallback_queue = fallback_queue
    _gcs_archiver = gcs_archiver
    _publisher = publisher
    _publish_retry_queue = publish_retry_queue
    logger.info(
        "MLLP pipeline initialised: archive_bucket=%s fallback_queue_capacity=%d pubsub_enabled=%s",
        gcs_archiver._bucket_name,
        500,
        publisher is not None,
    )


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

async def process_message(raw_hl7: str) -> bytes:
    """Process a raw HL7 ADT message through the full pipeline.

    Returns the MLLP-framed ACK (AA) or NACK (AE) bytes.

    The MLLP server (US-011/TASK-003) calls this coroutine for every
    successfully framed HL7 message.

    Step 1 — Extract MSH-10:
        Use a lightweight string split to get the message control ID
        without a full hl7apy parse.  The full parse happens in Step 4.

    Step 2 — Archive to GCS (SC-1):
        ``GCSArchiver.archive()`` is awaited before any other processing.
        The method handles retries and fallback internally.

    Step 3 — Idempotency check (SC-2):
        Query ``adt_event.source_message_id``.  On duplicate: return ACK.
        On DB error: log warning and continue (fail-open policy).

    Step 4 — Parse HL7 message:
        ``HL7Parser.parse()`` raises ``HL7ValidationError`` on bad messages.
        On parse failure: return NACK (AE).

    Step 5 — Route to handler:
        ``default_router.route()`` dispatches to the registered handler
        which persists the ``ADTEvent`` to the ``adt_event`` table.

    Step 6 — Publish to Pub/Sub (US-014):
        ``ADTEventPublisher.publish()`` dispatches the event to the
        ``adt-events`` topic with ``encounter_id`` as the ordering key.
        ACK is withheld until this step completes (SC-3).

    Step 7 — Return ACK (AA).
    """
    arrived_at = datetime.datetime.now(datetime.timezone.utc)

    # ------------------------------------------------------------------ #
    # Step 1: Extract MSH-10 (msg_control_id) from raw HL7
    # ------------------------------------------------------------------ #
    msg_control_id = _extract_msh10(raw_hl7)

    # ------------------------------------------------------------------ #
    # Step 2: Archive raw HL7 to GCS before ACK (SC-1 / AIR-003)
    # ------------------------------------------------------------------ #
    if _gcs_archiver is not None:
        await _gcs_archiver.archive(
            raw_hl7=raw_hl7,
            msg_control_id=msg_control_id,
            arrived_at=arrived_at,
        )
    else:
        logger.warning(
            "GCSArchiver not initialised — skipping archive for message_id=%s. "
            "Call init_pipeline() at startup.",
            msg_control_id,
        )

    # ------------------------------------------------------------------ #
    # Step 3: Idempotency check — skip if already processed (SC-2)
    # ------------------------------------------------------------------ #
    try:
        async with get_async_session() as session:
            if await _idempotency_checker.is_duplicate(session, msg_control_id):
                # Return ACK immediately — no further processing (DR-022)
                logger.info(
                    "Duplicate message detected — returning ACK without processing: message_id=%s",
                    msg_control_id,
                )
                return build_ack_response(raw_hl7)
    except SQLAlchemyError as exc:
        # Fail-open: DB error does not block HL7 ingestion
        logger.warning(
            "Idempotency check DB error for message_id=%s (%s) — treating as non-duplicate",
            msg_control_id,
            type(exc).__name__,
        )

    # ------------------------------------------------------------------ #
    # Step 4: Parse HL7 message
    # ------------------------------------------------------------------ #
    try:
        adt_event = _hl7_parser.parse(raw_hl7)
    except HL7ValidationError as exc:
        logger.warning(
            "HL7 validation failed for message_id=%s: %s",
            msg_control_id,
            str(exc),
        )
        return build_nack_response(raw_hl7, str(exc))

    # ------------------------------------------------------------------ #
    # Step 5: Route to registered handler (Pub/Sub publish stub)
    # ------------------------------------------------------------------ #
    try:
        default_router.route(adt_event)
    except Exception as exc:
        logger.error(
            "Handler routing failed for message_id=%s event_type=%s: %s",
            msg_control_id,
            adt_event.event_type.value,
            type(exc).__name__,
        )
        # Do not NACK — the message is archived; return ACK to stop EHR retransmission.

    # ------------------------------------------------------------------ #
    # Step 6: Publish ADTEvent to Pub/Sub adt-events topic  [US-014]
    #
    # ACK is withheld until publish() returns (US-014 SC-3).
    # publish() either:
    #   (a) succeeds directly or after retries → returns normally
    #   (b) exhausts all retries → enqueues to PublishRetryQueue → returns
    # In both cases, the event is durably handled before ACK is sent.
    # ------------------------------------------------------------------ #
    if _publisher is not None:
        await _publisher.publish(adt_event)
    else:
        logger.warning(
            "ADTEventPublisher not initialised — skipping Pub/Sub publish for message_id=%s. "
            "Call init_pipeline() with a publisher at startup.",
            msg_control_id,
        )

    # ------------------------------------------------------------------ #
    # Step 7: Return ACK
    # ------------------------------------------------------------------ #
    return build_ack_response(raw_hl7)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_msh10(raw_hl7: str) -> str:
    """Extract the MSH-10 message control ID from a raw HL7 string.

    Uses lightweight string splitting (no hl7apy overhead) since this runs
    before the full parse.  MSH is always the first segment; MSH-10 is the
    10th pipe-delimited field (0-indexed: index 9).

    Falls back to a timestamp-based placeholder if extraction fails — the
    archive and idempotency steps still proceed with the placeholder.

    Args:
        raw_hl7: Raw HL7 message text (MLLP framing already stripped).

    Returns:
        MSH-10 value string, or ``"UNKNOWN-{timestamp}"`` on extraction failure.
    """
    try:
        msh_segment = raw_hl7.split("\r")[0]
        fields = msh_segment.split("|")
        msg_control_id = fields[9].strip()
        if msg_control_id:
            return msg_control_id
    except (IndexError, AttributeError):
        pass

    # Fallback — generate a timestamp-based placeholder for archive path uniqueness
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
    fallback_id = f"UNKNOWN-{ts}"
    logger.warning(
        "Could not extract MSH-10 from raw HL7 — using fallback ID: %s",
        fallback_id,
    )
    return fallback_id
