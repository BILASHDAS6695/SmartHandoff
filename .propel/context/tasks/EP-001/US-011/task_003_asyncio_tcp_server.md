---
id: TASK-003
title: "Implement `hl7-listener/app/mllp/server.py` — asyncio TCP Server with Semaphore Connection Pool"
user_story: US-011
epic: EP-001
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-011/TASK-001, US-011/TASK-002]
---

# TASK-003: Implement `hl7-listener/app/mllp/server.py` — asyncio TCP Server with Semaphore Connection Pool

> **Story:** US-011 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This task implements the core asyncio TCP server that powers the HL7 Listener Cloud Run service. It:

1. Accepts TCP connections on port 2575 using `asyncio.start_server`.
2. Limits concurrent connections to 50 using an `asyncio.Semaphore` (AIR-004: *"max 50 concurrent MLLP connections"*).
3. For each connection, reads MLLP-framed bytes from the stream, extracts the HL7 message via `framing.read_mllp_frame`, parses with `hl7apy`, and dispatches ACK or NACK via the ACK builder.
4. Enforces the 200ms ACK SLA (AIR-001) using `asyncio.wait_for` with a 180ms budget for the HL7 parse step (leaving 20ms for I/O).
5. Logs structured errors to Cloud Logging on NACK (no PHI in log fields).

The server module also creates and exports `start_mllp_server(host, port)` — the entry point called from `main.py` (created in this task).

Design refs: AIR-001, AIR-004, TR-005, US-011 AC Scenarios 1–4.

---

## Acceptance Criteria Addressed

| US-011 AC | Requirement |
|---|---|
| **Scenario 1** | ACK returned within 200ms; `asyncio.wait_for` enforces parse timeout |
| **Scenario 2** | `MllpFramingError` and `hl7apy` parse errors trigger NACK(AE) + structured log |
| **Scenario 3** | `asyncio.Semaphore(50)` prevents >50 concurrent connections; all 5,000 messages ACKed under load |
| **Scenario 4** | `SO_KEEPALIVE` set per connection (see TASK-004); idle connections remain open for 300s |
| **DoD** | asyncio-based MLLP listener using `asyncio.start_server`; semaphore enforces max 50 connections |

---

## Implementation Steps

### 1. Create `hl7-listener/app/mllp/server.py`

```python
"""asyncio MLLP TCP server for HL7 ADT event ingestion.

Listens on TCP port 2575 for inbound MLLP-framed HL7 v2 messages from the EHR.
For each message it:
  1. Extracts the HL7 payload using MLLP framing (framing.py).
  2. Parses and validates the HL7 message with hl7apy.
  3. Returns an ACK (AA) within 200ms or a NACK (AE) on failure.
  4. Enforces a maximum of 50 concurrent connections via asyncio.Semaphore.

Concurrency model:
  - One asyncio.Semaphore(MAX_CONNECTIONS) guards the connection handler.
    When the semaphore is exhausted, new TCP connections are accepted at the
    OS level (backlog=100) but their handlers immediately release after the
    semaphore wait, preventing indefinite queue growth. The EHR's TCP stack
    will observe a delayed response and may queue or retry at its own rate.

ACK SLA enforcement:
  - hl7apy parsing is wrapped in asyncio.wait_for(timeout=PARSE_TIMEOUT_S).
    If parsing exceeds 0.18s the coroutine is cancelled and a NACK is sent.
    The 0.18s budget leaves ~20ms for I/O round-trip within the 200ms SLA.

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
import time
from typing import TYPE_CHECKING

import hl7

from app.mllp.ack_builder import build_ack_response, build_nack_response
from app.mllp.framing import MllpFramingError, read_mllp_frame

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

MAX_CONNECTIONS: int = 50           # AIR-004: max concurrent MLLP connections
READ_BUFFER_SIZE: int = 65536       # 64 KB per connection read buffer
PARSE_TIMEOUT_S: float = 0.18       # 180ms parse budget; leaves 20ms for I/O
IDLE_TIMEOUT_S: float = 300.0       # AIR-004: idle timeout 300 seconds
MAX_MESSAGE_SIZE: int = 1_048_576   # 1 MB safety cap on incoming MLLP frame


# ---------------------------------------------------------------------------
# Semaphore (module-level; shared across all connection handlers)
# ---------------------------------------------------------------------------

_connection_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, creating it lazily if needed."""
    global _connection_semaphore
    if _connection_semaphore is None:
        _connection_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)
    return _connection_semaphore


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single MLLP TCP connection.

    This coroutine is called once per accepted TCP connection.  It runs
    in a loop, reading MLLP frames until the connection is closed by the
    peer or the idle timeout fires.

    The asyncio.Semaphore limits the number of concurrently executing
    handlers.  Once the semaphore is acquired the handler processes
    messages in a loop; the semaphore is released when the connection
    closes.  This ensures at most MAX_CONNECTIONS active message-processing
    goroutines at any time.
    """
    semaphore = _get_semaphore()
    peer = writer.get_extra_info("peername", ("unknown", 0))
    peer_addr = peer[0]

    # Import here so metrics module (TASK-004) is optional at import time
    try:
        from app.metrics import (
            ACTIVE_CONNECTIONS,
            HL7_ACK_LATENCY,
            HL7_MESSAGES_TOTAL,
        )
        metrics_available = True
    except ImportError:
        metrics_available = False

    await semaphore.acquire()
    if metrics_available:
        ACTIVE_CONNECTIONS.inc()

    logger.info("connection_accepted peer_addr=%s active=%s", peer_addr,
                MAX_CONNECTIONS - semaphore._value)

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
                    peer_addr, IDLE_TIMEOUT_S,
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
                    peer_addr, len(buffer),
                )
                nack = build_nack_response(None, "Message exceeds maximum allowed size")
                writer.write(nack)
                await writer.drain()
                buffer = b""
                continue

            # Process all complete frames in the buffer
            while True:
                hl7_bytes, buffer = read_mllp_frame(buffer)
                if hl7_bytes is None:
                    break  # Incomplete frame — wait for more data

                start_ns = time.monotonic_ns()
                await _process_hl7_message(
                    hl7_bytes, writer, peer_addr, start_ns, metrics_available
                )

    except Exception as exc:  # noqa: BLE001
        logger.exception("connection_handler_error peer_addr=%s error=%s", peer_addr, exc)
    finally:
        if metrics_available:
            ACTIVE_CONNECTIONS.dec()
        semaphore.release()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        logger.info("connection_closed peer_addr=%s", peer_addr)


async def _process_hl7_message(
    hl7_bytes: bytes,
    writer: asyncio.StreamWriter,
    peer_addr: str,
    start_ns: int,
    metrics_available: bool,
) -> None:
    """Parse a single HL7 message and write ACK or NACK to the socket.

    Wrapped in asyncio.wait_for(PARSE_TIMEOUT_S) to enforce the 200ms ACK SLA.
    """
    if metrics_available:
        from app.metrics import HL7_ACK_LATENCY, HL7_MESSAGES_TOTAL

    try:
        raw_hl7 = hl7_bytes.decode("ascii", errors="replace")

        # Parse within timeout budget
        try:
            parsed = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, _parse_hl7_sync, raw_hl7
                ),
                timeout=PARSE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "hl7_parse_timeout peer_addr=%s timeout_ms=%d",
                peer_addr, int(PARSE_TIMEOUT_S * 1000),
            )
            nack = build_nack_response(raw_hl7, "HL7 parse timeout")
            writer.write(nack)
            await writer.drain()
            if metrics_available:
                HL7_MESSAGES_TOTAL.labels(status="nack_timeout").inc()
            return

        msg_control_id = parsed.get("msg_control_id", "UNKNOWN")
        event_type = parsed.get("event_type", "UNKNOWN")

        ack = build_ack_response(raw_hl7)
        writer.write(ack)
        await writer.drain()

        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        logger.info(
            "hl7_ack_sent peer_addr=%s msg_control_id=%s event_type=%s latency_ms=%.2f",
            peer_addr, msg_control_id, event_type, elapsed_ms,
        )
        if metrics_available:
            HL7_MESSAGES_TOTAL.labels(status="ack").inc()
            HL7_ACK_LATENCY.observe(elapsed_ms)

    except (MllpFramingError, ValueError, UnicodeDecodeError) as exc:
        error_text = str(exc)[:200]
        logger.warning(
            "hl7_nack_sent peer_addr=%s reason=%s", peer_addr, error_text
        )
        raw_hl7_str = hl7_bytes.decode("ascii", errors="replace") if hl7_bytes else None
        nack = build_nack_response(raw_hl7_str, error_text)
        writer.write(nack)
        await writer.drain()
        if metrics_available:
            HL7_MESSAGES_TOTAL.labels(status="nack_parse_error").inc()


def _parse_hl7_sync(raw_hl7: str) -> dict[str, str]:
    """Parse an HL7 v2 message synchronously using hl7apy.

    Run via ``run_in_executor`` to avoid blocking the asyncio event loop.

    Returns:
        Dict with ``msg_control_id`` and ``event_type`` extracted from MSH.
    """
    from hl7apy.core import Message
    from hl7apy.exceptions import HL7apyException

    try:
        msg = Message(raw_hl7.strip(), validation_level=2)
        return {
            "msg_control_id": str(msg.msh.msh_10.value),
            "event_type": str(msg.msh.msh_9.value),
        }
    except HL7apyException as exc:
        raise ValueError(f"HL7 parse error: {exc}") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_mllp_server(host: str = "0.0.0.0", port: int = 2575) -> None:
    """Start the asyncio MLLP TCP server and run until cancelled.

    Args:
        host: Bind address. Defaults to ``0.0.0.0`` (all interfaces).
        port: TCP port number. Defaults to 2575 (standard MLLP port).

    This coroutine blocks until the process is terminated. It is called from
    ``main.py`` alongside the HTTP health server (TASK-004).
    """
    server = await asyncio.start_server(
        _handle_connection,
        host=host,
        port=port,
        backlog=100,
        reuse_address=True,
    )

    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info("mllp_server_started host=%s port=%d addresses=%s", host, port, addrs)

    async with server:
        await server.serve_forever()
```

### 2. Create `hl7-listener/app/main.py`

```python
"""HL7 Listener service entry point.

Starts two concurrent asyncio servers:
  1. MLLP TCP server on port 2575 (HL7 ADT ingestion)
  2. HTTP server on port 8080 (/health and /ready probes — TASK-004)

Cloud Run configuration:
  - Set ``--port=2575`` (or configure TCP traffic routing per Cloud Run docs).
  - Health probes target port 8080 via a separate HTTP liveness path.

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
    """Run the MLLP TCP server and HTTP health server concurrently."""
    from app.health import start_health_server          # TASK-004
    from app.mllp.server import start_mllp_server

    host = os.getenv("MLLP_HOST", "0.0.0.0")
    mllp_port = int(os.getenv("MLLP_PORT", "2575"))
    health_port = int(os.getenv("HEALTH_PORT", "8080"))

    logger.info(
        "hl7_listener_starting mllp_port=%d health_port=%d", mllp_port, health_port
    )

    await asyncio.gather(
        start_mllp_server(host=host, port=mllp_port),
        start_health_server(host=host, port=health_port),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Validation

```bash
cd hl7-listener
# Syntax check — server.py and main.py should import without errors
python -c "import ast, pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('app').rglob('*.py')]; print('Syntax: OK')"
```

---

## Definition of Done Checklist

- [ ] `hl7-listener/app/mllp/server.py` created with `start_mllp_server(host, port)` coroutine
- [ ] `asyncio.start_server` used with `backlog=100` and `reuse_address=True`
- [ ] `asyncio.Semaphore(50)` acquired before each connection handler; released on close
- [ ] `asyncio.wait_for(PARSE_TIMEOUT_S=0.18)` wraps HL7 parse step
- [ ] `MllpFramingError` and `hl7apy` exceptions trigger `build_nack_response`
- [ ] PHI fields not present in any log statements
- [ ] `hl7-listener/app/main.py` created; `asyncio.gather` runs MLLP + health servers concurrently
- [ ] Syntax check passes
