"""asyncio MLLP TCP server for HL7 ADT event ingestion (US-011 / TASK-003).

Listens on TCP port 2575 for inbound MLLP-framed HL7 v2 messages from the EHR.
For each message it:
  1. Extracts the HL7 payload using MLLP framing (framing.py).
  2. Parses and validates the HL7 message synchronously via hl7apy in a
     thread-pool executor so the event loop is never blocked.
  3. Returns an ACK (AA) within 200ms or a NACK (AE) on failure.
  4. Enforces a maximum of 50 concurrent connections via asyncio.Semaphore.

Concurrency model:
  - asyncio.Semaphore(MAX_CONNECTIONS) guards the connection handler.
  - OS backlog=100 allows queuing without dropping SYN packets at peak.

ACK SLA enforcement (AIR-001):
  - hl7apy parsing is wrapped in asyncio.wait_for(timeout=PARSE_TIMEOUT_S=0.18).
    If parsing exceeds 180ms a NACK is sent; the 20ms remainder covers I/O.

TCP keep-alive (AIR-004, AC Scenario 4):
  - SO_KEEPALIVE + TCP_KEEPIDLE=30 / TCP_KEEPINTVL=10 / TCP_KEEPCNT=3
    applied to each accepted socket.

Idle timeout (AIR-004):
  - asyncio.wait_for(IDLE_TIMEOUT_S=300) on each chunk read; connection closed
    if no data arrives for 300 seconds.

Message size safety cap:
  - Frames >1 MB are rejected immediately with a NACK (prevents OOM).

Structured logging:
  - All log entries use key=value pairs.
  - PHI fields (patient name, DOB, MRN, phone, email) are NEVER logged.
  - Logged identifiers: message_control_id, event_type, peer_addr (IP only).

Design refs:
    AIR-001  — MLLP ACK within 200ms; NACK (AE) on parse failure
    AIR-004  — max 50 concurrent MLLP connections; idle timeout 300s
    TR-005   — ≥5,000 ADT events/day throughput
    US-011   — Build MLLP TCP Listener for HL7 ADT Event Ingestion
"""
from __future__ import annotations

import asyncio
import logging
import socket as _socket
import time

from app.mllp.ack_builder import build_ack_response, build_nack_response
from app.mllp.framing import MllpFramingError, read_mllp_frame

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

MAX_CONNECTIONS: int = 50           # AIR-004: max concurrent MLLP connections
READ_BUFFER_SIZE: int = 65536       # 64 KB per-read cap (prevents single-read spike)
PARSE_TIMEOUT_S: float = 0.18       # 180ms parse budget; leaves 20ms for I/O (AIR-001)
IDLE_TIMEOUT_S: float = 300.0       # AIR-004: close connection idle for 300s
MAX_MESSAGE_SIZE: int = 1_048_576   # 1 MB safety cap on accumulated MLLP frame

# ---------------------------------------------------------------------------
# Module-level semaphore (lazy-initialised on first connection in the loop)
# ---------------------------------------------------------------------------

_connection_semaphore: asyncio.Semaphore | None = None
_active_connection_count: int = 0  # Tracks active connections without using semaphore._value


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level connection semaphore, creating it if needed."""
    global _connection_semaphore
    if _connection_semaphore is None:
        _connection_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)
    return _connection_semaphore


# ---------------------------------------------------------------------------
# TCP keep-alive helper
# ---------------------------------------------------------------------------

def _apply_keepalive(writer: asyncio.StreamWriter) -> None:
    """Enable TCP keep-alive probes on the socket backing *writer*."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
    if hasattr(_socket, "TCP_KEEPIDLE"):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 30)
    if hasattr(_socket, "TCP_KEEPINTVL"):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10)
    if hasattr(_socket, "TCP_KEEPCNT"):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3)


# ---------------------------------------------------------------------------
# Per-message processor
# ---------------------------------------------------------------------------

async def _process_hl7_message(
    hl7_bytes: bytes,
    writer: asyncio.StreamWriter,
    peer_addr: str,
    start_ns: int,
) -> None:
    """Parse one HL7 message and write ACK or NACK to the socket.

    Delegates to ``app.mllp.pipeline.process_message()`` for the full
    archive → idempotency → parse → route pipeline (US-013).
    Wrapped in asyncio.wait_for(PARSE_TIMEOUT_S) to enforce the 200ms ACK SLA.
    """
    from app.metrics import HL7_ACK_LATENCY, HL7_MESSAGES_TOTAL
    from app.mllp.pipeline import process_message

    raw_hl7_str: str | None = None
    try:
        raw_hl7_str = hl7_bytes.decode("ascii", errors="replace")

        # Run full pipeline within timeout budget (AIR-001: 200ms ACK SLA)
        try:
            ack_or_nack = await asyncio.wait_for(
                process_message(raw_hl7_str),
                timeout=PARSE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "hl7_pipeline_timeout peer_addr=%s timeout_ms=%d",
                peer_addr,
                int(PARSE_TIMEOUT_S * 1000),
            )
            nack = build_nack_response(raw_hl7_str, "HL7 pipeline timeout")
            writer.write(nack)
            await writer.drain()
            HL7_MESSAGES_TOTAL.labels(status="nack_timeout").inc()
            return

        writer.write(ack_or_nack)
        await writer.drain()

        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        # Determine whether we sent an ACK (AA) or NACK (AE) for metrics
        status = "ack" if b"MSA|AA" in ack_or_nack else "nack_parse_error"
        HL7_MESSAGES_TOTAL.labels(status=status).inc()
        HL7_ACK_LATENCY.observe(elapsed_ms)
        logger.info(
            "hl7_response_sent peer_addr=%s status=%s latency_ms=%.2f",
            peer_addr,
            status,
            elapsed_ms,
        )

    except (MllpFramingError, ValueError, UnicodeDecodeError) as exc:
        error_text = str(exc)[:200]
        logger.warning(
            "hl7_nack_sent peer_addr=%s reason=%s", peer_addr, error_text
        )
        nack = build_nack_response(raw_hl7_str, error_text)
        writer.write(nack)
        await writer.drain()
        HL7_MESSAGES_TOTAL.labels(status="nack_parse_error").inc()


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single MLLP TCP connection with semaphore gate.

    Persistent connections (keep-alive) are supported: the loop continues
    until EOF, idle timeout, or an unrecoverable error.
    """
    semaphore = _get_semaphore()
    peer = writer.get_extra_info("peername", ("unknown", 0))
    peer_addr: str = peer[0]

    from app.metrics import ACTIVE_CONNECTIONS

    await semaphore.acquire()
    global _active_connection_count
    _active_connection_count += 1
    _apply_keepalive(writer)
    ACTIVE_CONNECTIONS.inc()

    logger.info(
        "connection_accepted peer_addr=%s active=%d",
        peer_addr,
        _active_connection_count,
    )

    buffer = b""
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(
                    reader.read(READ_BUFFER_SIZE),
                    timeout=IDLE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "connection_idle_timeout peer_addr=%s timeout_s=%s",
                    peer_addr,
                    IDLE_TIMEOUT_S,
                )
                break

            if not chunk:
                logger.info("connection_closed_by_peer peer_addr=%s", peer_addr)
                break

            buffer += chunk

            # Safety cap — reject oversized messages before attempting parse
            if len(buffer) > MAX_MESSAGE_SIZE:
                logger.error(
                    "message_too_large peer_addr=%s size_bytes=%d",
                    peer_addr,
                    len(buffer),
                )
                from app.metrics import HL7_MESSAGES_TOTAL
                nack = build_nack_response(None, "Message exceeds maximum allowed size")
                writer.write(nack)
                await writer.drain()
                HL7_MESSAGES_TOTAL.labels(status="nack_oversized").inc()
                buffer = b""
                continue

            # Process all complete frames accumulated in the buffer
            while True:
                hl7_bytes, buffer = read_mllp_frame(buffer)
                if hl7_bytes is None:
                    break  # Incomplete frame — wait for more data

                start_ns = time.monotonic_ns()
                await _process_hl7_message(hl7_bytes, writer, peer_addr, start_ns)

    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "connection_handler_error peer_addr=%s error=%s", peer_addr, exc
        )
    finally:
        ACTIVE_CONNECTIONS.dec()
        _active_connection_count -= 1
        semaphore.release()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        logger.info("connection_closed peer_addr=%s", peer_addr)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_mllp_server(host: str = "0.0.0.0", port: int = 2575) -> None:
    """Start the asyncio MLLP TCP server and run until cancelled.

    Args:
        host: Bind address. Defaults to ``0.0.0.0`` (all interfaces).
        port: TCP port number. Defaults to 2575 (standard MLLP port).

    This coroutine blocks until the process is terminated. It is called from
    ``app/main.py`` alongside the HTTP health server.
    """
    server = await asyncio.start_server(
        _handle_connection,
        host=host,
        port=port,
        backlog=100,
        reuse_address=True,
    )

    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(
        "mllp_server_started host=%s port=%d addresses=%s max_connections=%d",
        host,
        port,
        addrs,
        MAX_CONNECTIONS,
    )

    async with server:
        await server.serve_forever()
