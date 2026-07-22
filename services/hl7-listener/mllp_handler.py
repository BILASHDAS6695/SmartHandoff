"""
services/hl7-listener/mllp_handler.py

Asyncio MLLP ADT message handler (US-011).

Responsibilities:
- Parse raw HL7 v2 bytes and extract MSH fields
- Validate that a MSH segment is present (raises ValueError → NACK on failure)
- Publish the parsed payload to Cloud Pub/Sub with W3C trace context injected
- Return (control_id, ack_text) so the caller can write the MLLP frame
- Create an OpenTelemetry SERVER span per message for distributed tracing
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.propagate import inject

from shared.otel import get_tracer

logger = logging.getLogger(__name__)

PUBSUB_TOPIC: str = os.environ.get("PUBSUB_TOPIC", "")


# ── HL7 v2 MSH parser ────────────────────────────────────────────────────────

def parse_hl7(raw_hl7: bytes) -> dict[str, str]:
    """
    Parse raw HL7 v2 bytes and extract key MSH fields.

    Returns a dict with keys:
        message_type, event_type, message_control_id, payload

    Raises:
        ValueError: If the message does not contain a valid MSH segment.
    """
    text = raw_hl7.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    msh_line: str | None = None
    for line in lines:
        if line.startswith("MSH"):
            msh_line = line
            break

    if msh_line is None:
        raise ValueError("Missing MSH segment — message cannot be parsed")

    fields = msh_line.split("|")

    # MSH.9 — Message Type ^ Event Type
    message_type = "unknown"
    event_type = "unknown"
    if len(fields) > 8:
        msg_type_field = fields[8].split("^")
        message_type = msg_type_field[0] if msg_type_field else "unknown"
        event_type = msg_type_field[1] if len(msg_type_field) > 1 else "unknown"

    # MSH.10 — Message Control ID
    message_control_id = fields[9] if len(fields) > 9 else ""

    return {
        "message_type": message_type,
        "event_type": event_type,
        "message_control_id": message_control_id,
        "payload": text,
    }


# ── Pub/Sub publisher ─────────────────────────────────────────────────────────

def _publish_to_pubsub(message_data: dict[str, str], carrier: dict[str, str]) -> None:
    """Publish parsed HL7 payload to the configured Pub/Sub topic."""
    if not PUBSUB_TOPIC:
        logger.warning("PUBSUB_TOPIC not set — skipping publish")
        return

    from google.cloud import pubsub_v1  # type: ignore[import]

    publisher = pubsub_v1.PublisherClient()
    attributes: dict[str, str] = {
        k: v
        for k, v in {
            "traceparent": carrier.get("traceparent", ""),
            "tracestate": carrier.get("tracestate", ""),
            "event_type": message_data.get("event_type", ""),
            "message_type": message_data.get("message_type", ""),
        }.items()
        if v
    }
    publisher.publish(
        PUBSUB_TOPIC,
        data=message_data["payload"].encode("utf-8"),
        **attributes,
    )


# ── Async message processor ───────────────────────────────────────────────────

async def process_adt_message(raw_hl7: bytes) -> tuple[str, str]:
    """
    Process a single MLLP ADT message and return ``(control_id, ack_text)``.

    Opens an OpenTelemetry SERVER span for distributed tracing.
    Injects W3C trace context into Pub/Sub message attributes.

    Args:
        raw_hl7: Raw HL7 v2 bytes stripped of MLLP framing.

    Returns:
        A tuple of (message_control_id, ack_hl7_text).

    Raises:
        ValueError: If the message lacks an MSH segment (caller sends NACK).
        Exception:  Any other processing failure (caller sends NACK).
    """
    tracer = get_tracer(__name__)

    with tracer.start_as_current_span(
        "hl7-listener.process_adt_message",
        kind=trace.SpanKind.SERVER,
    ) as span:
        # Parse — raises ValueError on bad message (triggers NACK in caller)
        message_data = parse_hl7(raw_hl7)

        span.set_attribute("hl7.message_type", message_data["message_type"])
        span.set_attribute("hl7.event_type", message_data["event_type"])
        span.set_attribute("hl7.message_control_id", message_data["message_control_id"])

        # Inject W3C trace context for Pub/Sub propagation
        carrier: dict[str, str] = {}
        inject(carrier)

        # Publish to Pub/Sub in a thread-pool executor (blocking SDK)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _publish_to_pubsub, message_data, carrier
        )

        control_id = message_data["message_control_id"]
        from app.mllp.ack_builder import build_ack_response  # noqa: PLC0415
        ack_bytes = build_ack_response(message_data["payload"])
        ack_text = ack_bytes.decode("utf-8", errors="replace")

        logger.info(
            "ADT message processed and published",
            extra={
                "event_type": message_data["event_type"],
                "message_control_id": control_id,
            },
        )
        return control_id, ack_text
