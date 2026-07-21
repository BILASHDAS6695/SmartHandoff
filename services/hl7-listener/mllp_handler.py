"""
services/hl7-listener/mllp_handler.py

MLLP ADT message handler with OpenTelemetry distributed trace propagation.

Each incoming HL7 ADT message is wrapped in a root SERVER span.  The trace
context is injected into outgoing Pub/Sub message attributes using the W3C
Trace Context format so downstream agents (coordinator-agent, docs-agent, etc.)
can continue the trace as CONSUMER child spans.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.propagate import inject

from shared.otel import get_tracer

if TYPE_CHECKING:
    import socket

logger = logging.getLogger(__name__)


def handle_adt_message(raw_hl7: bytes, conn: "socket.socket") -> None:
    """
    Process a single MLLP ADT message, publish to Pub/Sub, and send ACK.

    Opens a root OpenTelemetry span for the full processing pipeline.
    Injects trace context into Pub/Sub message attributes so downstream
    agents continue the same distributed trace.

    Args:
        raw_hl7: Raw HL7 v2 bytes stripped of MLLP framing characters.
        conn:    Open MLLP TCP connection — used to send ACK/NACK back to sender.
    """
    tracer = get_tracer(__name__)

    with tracer.start_as_current_span(
        "hl7-listener.process_adt_message",
        kind=trace.SpanKind.SERVER,
    ) as span:
        try:
            message_data = _parse_hl7(raw_hl7)
            span.set_attribute("hl7.message_type", message_data.get("message_type", "unknown"))
            span.set_attribute("hl7.event_type", message_data.get("event_type", "unknown"))

            # Inject W3C trace context into Pub/Sub attributes for propagation
            carrier: dict[str, str] = {}
            inject(carrier)

            _publish_to_pubsub(message_data, carrier)

            _send_ack(conn, message_data.get("message_control_id", ""))
            logger.info(
                "ADT message processed and published",
                extra={"event_type": message_data.get("event_type")},
            )

        except Exception:
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            logger.exception("Failed to process ADT message")
            _send_nack(conn)


def _parse_hl7(raw_hl7: bytes) -> dict[str, str]:
    """
    Minimal HL7 v2 MSH segment parser — extracts message type and control ID.

    Returns a dict with keys: message_type, event_type, message_control_id, payload.
    """
    text = raw_hl7.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    result: dict[str, str] = {
        "message_type": "unknown",
        "event_type": "unknown",
        "message_control_id": "",
        "payload": text,
    }

    for line in lines:
        if line.startswith("MSH"):
            fields = line.split("|")
            if len(fields) > 9:
                # MSH.9: Message Type^Event Type
                msg_type_field = fields[8].split("^")
                result["message_type"] = msg_type_field[0] if msg_type_field else "unknown"
                result["event_type"] = msg_type_field[1] if len(msg_type_field) > 1 else "unknown"
            if len(fields) > 10:
                result["message_control_id"] = fields[9]
            break

    return result


def _publish_to_pubsub(message_data: dict[str, str], carrier: dict[str, str]) -> None:
    """Publish parsed HL7 payload to the configured Pub/Sub topic."""
    from google.cloud import pubsub_v1  # type: ignore[import]

    topic = os.environ.get("PUBSUB_TOPIC", "")
    if not topic:
        logger.warning("PUBSUB_TOPIC not set — skipping publish")
        return

    publisher = pubsub_v1.PublisherClient()
    attributes = {
        "traceparent": carrier.get("traceparent", ""),
        "tracestate": carrier.get("tracestate", ""),
        "event_type": message_data.get("event_type", ""),
        "message_type": message_data.get("message_type", ""),
    }
    publisher.publish(
        topic,
        data=message_data["payload"].encode("utf-8"),
        **{k: v for k, v in attributes.items() if v},
    )


def _send_ack(conn: "socket.socket", control_id: str) -> None:
    """Send MLLP ACK (AA) back to the sending system."""
    ack = (
        f"MSH|^~\\&|SmartHandoff|HL7Listener|Sender|System|"
        f"||||ACK||P|2.5\r"
        f"MSA|AA|{control_id}|Message accepted\r"
    )
    conn.sendall(b"\x0b" + ack.encode("utf-8") + b"\x1c\x0d")


def _send_nack(conn: "socket.socket") -> None:
    """Send MLLP NACK (AE) back to the sending system on processing error."""
    nack = (
        "MSH|^~\\&|SmartHandoff|HL7Listener|Sender|System|"
        "||||ACK||P|2.5\r"
        "MSA|AE||Processing error — message not accepted\r"
    )
    conn.sendall(b"\x0b" + nack.encode("utf-8") + b"\x1c\x0d")
