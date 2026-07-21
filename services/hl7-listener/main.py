"""
services/hl7-listener/main.py

HL7 MLLP Listener Cloud Run service entry point.

This service runs a raw TCP MLLP server (not HTTP/FastAPI) so observability
uses manual span creation rather than FastAPI middleware.  Trace context is
injected into outgoing Pub/Sub message attributes so downstream agents
(coordinator-agent etc.) can continue the distributed trace as child spans.
"""
from __future__ import annotations

import os

from shared.otel import init_tracer
from shared.logging import configure_logging

# ── Observability bootstrap ───────────────────────────────────────────────────
# Must run before any MLLP server socket is opened.
SERVICE_NAME = os.environ.get("K_SERVICE", "hl7-listener")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)
# ─────────────────────────────────────────────────────────────────────────────

import logging  # noqa: E402  (import after logging configured)

logger = logging.getLogger(__name__)

MLLP_PORT = int(os.environ.get("MLLP_PORT", "2575"))
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "")


def start_mllp_server() -> None:
    """
    Start the MLLP TCP server loop.

    Each ADT message received is wrapped in an OpenTelemetry span by
    ``mllp_handler.handle_adt_message()``.  See ``mllp_handler.py`` for the
    span creation and trace-context propagation pattern.
    """
    import socket

    logger.info("Starting MLLP server on port %d", MLLP_PORT)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("0.0.0.0", MLLP_PORT))
    server_socket.listen(5)

    logger.info("MLLP server listening on 0.0.0.0:%d", MLLP_PORT)

    while True:
        conn, addr = server_socket.accept()
        logger.info("MLLP connection from %s", addr[0])
        _handle_connection(conn)


def _handle_connection(conn) -> None:
    """Read one MLLP frame and dispatch to the message handler."""
    from mllp_handler import handle_adt_message

    try:
        data = _read_mllp_frame(conn)
        if data:
            handle_adt_message(raw_hl7=data, conn=conn)
    except Exception:
        logger.exception("Error processing MLLP connection")
    finally:
        conn.close()


def _read_mllp_frame(conn) -> bytes | None:
    """Read bytes until MLLP end-of-block (0x1C 0x0D)."""
    MLLP_SB = b"\x0b"   # Start Block
    MLLP_EB = b"\x1c"   # End Block
    MLLP_CR = b"\x0d"   # Carriage Return

    buf = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        buf += chunk
        if MLLP_EB + MLLP_CR in buf:
            return buf.lstrip(MLLP_SB).split(MLLP_EB)[0]


if __name__ == "__main__":
    start_mllp_server()
