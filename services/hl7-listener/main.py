"""
services/hl7-listener/main.py

HL7 MLLP Listener — asyncio-based TCP server (US-011).

Architecture:
- asyncio.start_server on port 2575 (MLLP_PORT env)
- Max 50 concurrent connections enforced via asyncio.Semaphore
- TCP keep-alive enabled on every accepted socket
- MLLP framing: VT (0x0B) start-block, FS (0x1C) end-block, CR (0x0D)
- ACK (AA) returned within 200 ms SLA (AIR-001)
- NACK (AE) + ERR segment returned on parse / processing failure
- Prometheus metrics: hl7_messages_total, hl7_ack_latency_ms, hl7_active_connections
- Asyncio HTTP mini-server for GET /health and GET /ready (HEALTH_PORT, default 8080)
- Prometheus metrics exposed on METRICS_PORT (default 9090)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from datetime import datetime, timezone

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from shared.otel import init_tracer
from shared.logging import configure_logging
from app.handlers import register_cancellation_handlers

# ── Observability bootstrap ───────────────────────────────────────────────────
# Must run before any MLLP server socket is opened.
SERVICE_NAME = os.environ.get("K_SERVICE", "hl7-listener")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)
# ─────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
MLLP_PORT: int = int(os.environ.get("MLLP_PORT", "2575"))
METRICS_PORT: int = int(os.environ.get("METRICS_PORT", "9090"))
HEALTH_PORT: int = int(os.environ.get("HEALTH_PORT", "8080"))
MAX_CONNECTIONS: int = int(os.environ.get("MAX_CONNECTIONS", "50"))
PUBSUB_TOPIC: str = os.environ.get("PUBSUB_TOPIC", "")

# ── Prometheus metrics ────────────────────────────────────────────────────────
HL7_MESSAGES_TOTAL = Counter(
    "hl7_messages_total",
    "Total HL7 messages received",
    ["status"],  # labels: ack | nack
)
HL7_ACK_LATENCY_MS = Histogram(
    "hl7_ack_latency_ms",
    "Latency in milliseconds from message receipt to ACK/NACK sent",
    buckets=[10, 25, 50, 100, 150, 200, 300, 500, 1000],
)
HL7_ACTIVE_CONNECTIONS = Gauge(
    "hl7_active_connections",
    "Number of currently active MLLP TCP connections",
)

# ── Connection semaphore (initialised in _amain) ──────────────────────────────
_connection_semaphore: asyncio.Semaphore

# ── MLLP framing constants ────────────────────────────────────────────────────
MLLP_VT: int = 0x0B  # Vertical Tab  — Start Block
MLLP_FS: int = 0x1C  # File Separator — End Block
MLLP_CR: int = 0x0D  # Carriage Return


# ── TCP keep-alive helper ─────────────────────────────────────────────────────

def _enable_tcp_keepalive(sock: socket.socket) -> None:
    """Enable TCP keep-alive probes on *sock* (platform-agnostic)."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)


# ── MLLP frame reader ─────────────────────────────────────────────────────────

async def _read_mllp_frame(reader: asyncio.StreamReader) -> bytes | None:
    """
    Read one MLLP frame from *reader*.

    MLLP framing: VT (0x0B) ... <HL7 bytes> ... FS (0x1C) CR (0x0D)

    Returns the raw HL7 bytes without framing characters, or ``None`` when
    the peer closes the connection cleanly.

    Raises:
        ValueError: If the stream does not begin with the VT start-block byte.
    """
    try:
        first_byte = await reader.readexactly(1)
    except asyncio.IncompleteReadError:
        return None  # clean EOF

    if first_byte[0] != MLLP_VT:
        raise ValueError(
            f"Invalid MLLP start byte: 0x{first_byte[0]:02X} (expected 0x{MLLP_VT:02X})"
        )

    buf = bytearray()
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            return None  # connection closed mid-frame
        buf.extend(chunk)
        if MLLP_FS in buf:
            fs_idx = buf.index(MLLP_FS)
            return bytes(buf[:fs_idx])


# ── MLLP frame writer ─────────────────────────────────────────────────────────

def _wrap_mllp(payload: bytes) -> bytes:
    """Wrap *payload* in MLLP framing bytes: VT + payload + FS + CR."""
    return bytes([MLLP_VT]) + payload + bytes([MLLP_FS, MLLP_CR])


# ── HL7 ACK / NACK builders ───────────────────────────────────────────────────

def _hl7_timestamp() -> str:
    """Return current UTC time in HL7 DTM format (YYYYMMDDHHmmss)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def build_ack(control_id: str) -> str:
    """
    Build an HL7 v2.5 ACK message with acknowledgement code AA.

    MSH-9 = ACK, MSA-1 = AA, MSA-2 = original MSH-10 (message control ID).
    """
    ts = _hl7_timestamp()
    return (
        f"MSH|^~\\&|SmartHandoff|HL7Listener|EHR|System|{ts}||ACK|{control_id}_ACK|P|2.5\r"
        f"MSA|AA|{control_id}|Message accepted successfully\r"
    )


def build_nack(
    control_id: str,
    error_code: str = "207",
    error_text: str = "Application error",
) -> str:
    """
    Build an HL7 v2.5 NACK message with acknowledgement code AE + ERR segment.

    Error code 207 = Application error (HL7 table 0357).
    """
    ts = _hl7_timestamp()
    return (
        f"MSH|^~\\&|SmartHandoff|HL7Listener|EHR|System|{ts}||ACK|{control_id}_NACK|P|2.5\r"
        f"MSA|AE|{control_id}|{error_text}\r"
        f"ERR|||{error_code}^{error_text}^HL70357\r"
    )


# ── Per-message processor ─────────────────────────────────────────────────────

async def _process_one_message(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    peer: tuple[str, int],
) -> None:
    """Read one MLLP frame, process it, and write ACK or NACK."""
    from mllp_handler import process_adt_message  # lazy import to avoid circular

    t0 = time.monotonic()
    status = "nack"
    try:
        raw = await _read_mllp_frame(reader)
    except ValueError as exc:
        logger.warning("MLLP framing error from %s: %s", peer[0], exc)
        nack = build_nack("", "207", str(exc))
        writer.write(_wrap_mllp(nack.encode("utf-8")))
        await writer.drain()
        HL7_MESSAGES_TOTAL.labels(status="nack").inc()
        HL7_ACK_LATENCY_MS.observe((time.monotonic() - t0) * 1000)
        return

    if raw is None:
        return  # connection closed

    try:
        control_id, ack_payload = await process_adt_message(raw)
        writer.write(_wrap_mllp(ack_payload.encode("utf-8")))
        await writer.drain()
        status = "ack"
    except Exception as exc:
        logger.exception("Failed to process HL7 message from %s", peer[0])
        nack_text = build_nack("", "207", f"Application error: {exc}")
        writer.write(_wrap_mllp(nack_text.encode("utf-8")))
        await writer.drain()
        status = "nack"
    finally:
        HL7_MESSAGES_TOTAL.labels(status=status).inc()
        HL7_ACK_LATENCY_MS.observe((time.monotonic() - t0) * 1000)


# ── Connection handler ────────────────────────────────────────────────────────

async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """
    Manage a single persistent MLLP TCP connection.

    Loops until the peer closes the connection, processing one message per
    iteration.  TCP keep-alive is enabled to maintain idle connections.
    """
    peer: tuple[str, int] = writer.get_extra_info("peername", ("unknown", 0))
    logger.info("MLLP connection accepted from %s:%s", peer[0], peer[1])

    sock: socket.socket | None = writer.get_extra_info("socket")
    if sock:
        _enable_tcp_keepalive(sock)

    HL7_ACTIVE_CONNECTIONS.inc()
    try:
        while not reader.at_eof():
            await _process_one_message(reader, writer, peer)
    except asyncio.CancelledError:
        logger.warning("Connection from %s cancelled", peer[0])
        raise
    except Exception:
        logger.exception("Unhandled error on connection from %s", peer[0])
    finally:
        HL7_ACTIVE_CONNECTIONS.dec()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("MLLP connection closed from %s:%s", peer[0], peer[1])


async def _gated_handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """
    Gate connections through the semaphore (max MAX_CONNECTIONS active).

    Connections that exceed the limit are logged and closed immediately.
    """
    if _connection_semaphore.locked():
        peer = writer.get_extra_info("peername", ("unknown", 0))
        logger.warning(
            "Connection limit (%d) reached; rejecting connection from %s",
            MAX_CONNECTIONS,
            peer[0],
        )
        try:
            nack = build_nack("", "207", "Server at connection capacity")
            writer.write(_wrap_mllp(nack.encode("utf-8")))
            await writer.drain()
            writer.close()
        except Exception:
            pass
        return

    async with _connection_semaphore:
        await _handle_connection(reader, writer)


# ── Health / ready HTTP mini-server ──────────────────────────────────────────

async def _health_handler(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Minimal HTTP/1.1 handler that serves GET /health and GET /ready."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        line = request_line.decode("utf-8", errors="replace").strip()
        parts = line.split()
        path = parts[1] if len(parts) >= 2 else "/"

        if path in ("/health", "/ready"):
            body = b'{"status":"ok"}'
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body
            )
        else:
            response = b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n"

        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ── Asyncio entry point ───────────────────────────────────────────────────────

async def _amain() -> None:
    """Start MLLP TCP server, health HTTP server, and Prometheus metrics."""
    global _connection_semaphore
    _connection_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)

    # Register ADT cancellation event handlers (A11, A12, A13) — US-015
    register_cancellation_handlers()

    # Prometheus metrics HTTP server runs in a thread-pool executor
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_http_server, METRICS_PORT)
    logger.info("Prometheus metrics server started on port %d", METRICS_PORT)

    # Health / readiness HTTP server
    health_srv = await asyncio.start_server(
        _health_handler,
        host="0.0.0.0",
        port=HEALTH_PORT,
    )
    logger.info("Health HTTP server listening on 0.0.0.0:%d", HEALTH_PORT)

    # MLLP TCP server
    mllp_srv = await asyncio.start_server(
        _gated_handle_connection,
        host="0.0.0.0",
        port=MLLP_PORT,
        limit=2 ** 20,  # 1 MiB read buffer per connection
    )
    logger.info(
        "MLLP server listening on 0.0.0.0:%d (max %d concurrent connections)",
        MLLP_PORT,
        MAX_CONNECTIONS,
    )

    async with mllp_srv, health_srv:
        await asyncio.gather(
            mllp_srv.serve_forever(),
            health_srv.serve_forever(),
        )


def main() -> None:
    """Synchronous entry point — launches the asyncio event loop."""
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("MLLP listener shutting down")


if __name__ == "__main__":
    main()
