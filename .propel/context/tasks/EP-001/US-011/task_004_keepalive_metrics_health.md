---
id: TASK-004
title: "Add TCP Keep-Alive, Prometheus Metrics, and HTTP `/health` + `/ready` Endpoints"
user_story: US-011
epic: EP-001
sprint: 1
layer: Backend / Observability
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-011/TASK-003]
---

# TASK-004: Add TCP Keep-Alive, Prometheus Metrics, and HTTP `/health` + `/ready` Endpoints

> **Story:** US-011 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend / Observability | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

Three infrastructure concerns left after the TCP server is functional:

**1. TCP Keep-Alive (AIR-004, AC Scenario 4)**
> *"TCP keep-alive enabled; max 50 concurrent MLLP connections; idle timeout 300 seconds"*

The EHR holds persistent MLLP connections across many messages. Without `SO_KEEPALIVE`, a connection idle for >300 seconds may be silently dropped by the network path (NAT timeout, firewall idle timeout). `SO_KEEPALIVE` sends OS-level probes to detect dead peers, and `TCP_KEEPIDLE` / `TCP_KEEPINTVL` / `TCP_KEEPCNT` tune the probe schedule.

**2. Prometheus Metrics (US-011 DoD)**
> *"Prometheus metrics exposed: `hl7_messages_total`, `hl7_ack_latency_ms`, `hl7_active_connections`"*

Cloud Monitoring scrapes the `/metrics` Prometheus endpoint. The server module (TASK-003) already imports from `app.metrics` — this task creates that module.

**3. HTTP Health/Ready Endpoints (US-011 DoD, TR-016)**
> *"GET /health and GET /ready endpoints implemented as asyncio HTTP server"*

Cloud Run probes these paths every 5–10 seconds (TR-016). They run on port 8080 in the same asyncio event loop as the MLLP server, using a minimal `asyncio` HTTP server (no framework dependency).

Design refs: AIR-004, TR-016, US-011 DoD.

---

## Acceptance Criteria Addressed

| US-011 AC | Requirement |
|---|---|
| **Scenario 4** | Keep-alive probes maintain idle connection; `SO_KEEPALIVE + TCP_KEEPIDLE=30` |
| **DoD** | Prometheus metrics: `hl7_messages_total`, `hl7_ack_latency_ms`, `hl7_active_connections` |
| **DoD** | `GET /health` and `GET /ready` endpoints on port 8080 |

---

## Implementation Steps

### 1. Create `hl7-listener/app/metrics.py`

```python
"""Prometheus metrics for the HL7 Listener service.

Exposes three metrics consumed by Cloud Monitoring (GCP Prometheus scrape):

  hl7_messages_total{status}  — Counter; status: "ack" | "nack_parse_error" | "nack_timeout"
  hl7_ack_latency_ms          — Histogram; ACK round-trip latency in milliseconds
  hl7_active_connections      — Gauge; current number of active MLLP connections

The /metrics HTTP endpoint is served by the health server (health.py) on port 8080
alongside /health and /ready.

Design refs:
    US-011 DoD — Prometheus metrics: hl7_messages_total, hl7_ack_latency_ms, hl7_active_connections
    TR-016     — Health probes / observability
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HL7_MESSAGES_TOTAL: Counter = Counter(
    name="hl7_messages_total",
    documentation="Total HL7 messages processed, labelled by outcome status.",
    labelnames=["status"],
    # status values: "ack" | "nack_parse_error" | "nack_timeout" | "nack_oversized"
)

HL7_ACK_LATENCY: Histogram = Histogram(
    name="hl7_ack_latency_ms",
    documentation=(
        "End-to-end ACK latency in milliseconds, measured from TCP payload receipt "
        "to ACK bytes written to socket. SLA target: <200ms (AIR-001)."
    ),
    buckets=[10, 25, 50, 100, 150, 200, 250, 500, 1000],
)

ACTIVE_CONNECTIONS: Gauge = Gauge(
    name="hl7_active_connections",
    documentation="Current number of active MLLP TCP connections.",
)
```

### 2. Add Keep-Alive to the TCP server connection handler

Open `hl7-listener/app/mllp/server.py` and add the keep-alive socket configuration in the `_handle_connection` coroutine, **immediately after** the `await semaphore.acquire()` line:

```python
# --- TCP keep-alive configuration (AIR-004, AC Scenario 4) ---
import socket as _socket
sock = writer.get_extra_info("socket")
if sock is not None:
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
    # TCP_KEEPIDLE: seconds before first probe after last data (Linux/macOS)
    if hasattr(_socket, "TCP_KEEPIDLE"):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 30)
    # TCP_KEEPINTVL: seconds between subsequent probes
    if hasattr(_socket, "TCP_KEEPINTVL"):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10)
    # TCP_KEEPCNT: number of failed probes before declaring the connection dead
    if hasattr(_socket, "TCP_KEEPCNT"):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3)
```

> **Platform note:** `TCP_KEEPIDLE` is available on Linux (GCP Cloud Run) and macOS 10.8+. The `hasattr` guards make the code portable without raising `AttributeError` on Windows.

### 3. Create `hl7-listener/app/health.py`

```python
"""Minimal asyncio HTTP server exposing /health, /ready, and /metrics endpoints.

Runs on port 8080 in the same asyncio event loop as the MLLP TCP server (main.py).
Cloud Run health probes (TR-016):
  - Liveness:   GET /health  → 200 OK
  - Readiness:  GET /ready   → 200 OK
  - Metrics:    GET /metrics → 200 OK (Prometheus text format)

The server uses only stdlib asyncio — no external HTTP framework dependency.
This keeps the container image lean (no aiohttp, starlette, etc.) and the
startup time under 1 second.

Design refs:
    TR-016   — Health check: GET /health every 10s, GET /ready every 5s
    US-011   — DoD: GET /health and GET /ready as asyncio HTTP server
"""
from __future__ import annotations

import asyncio
import logging

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = logging.getLogger(__name__)

_HTTP_200 = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"
_HTTP_404 = b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nNot found"


async def _handle_http(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single HTTP request from the Cloud Run health probe."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        request_str = request_line.decode("ascii", errors="replace").strip()

        # Consume remaining headers (we don't need them for health checks)
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not line or line == b"\r\n":
                break

        # Parse method and path from "GET /health HTTP/1.1"
        parts = request_str.split()
        path = parts[1] if len(parts) >= 2 else "/"

        if path in ("/health", "/ready"):
            writer.write(_HTTP_200 + b"OK")
            logger.debug("health_probe_ok path=%s", path)

        elif path == "/metrics":
            metrics_bytes = generate_latest()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: " + CONTENT_TYPE_LATEST.encode() + b"\r\n"
                b"\r\n" + metrics_bytes
            )
            writer.write(response)
            logger.debug("metrics_scraped bytes=%d", len(metrics_bytes))

        else:
            writer.write(_HTTP_404)

    except asyncio.TimeoutError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_server_error error=%s", exc)
    finally:
        try:
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def start_health_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the HTTP health/metrics server and run until cancelled.

    Args:
        host: Bind address. Defaults to ``0.0.0.0``.
        port: TCP port for HTTP. Defaults to 8080.
    """
    server = await asyncio.start_server(
        _handle_http,
        host=host,
        port=port,
        reuse_address=True,
    )
    logger.info("health_server_started host=%s port=%d", host, port)

    async with server:
        await server.serve_forever()
```

### 4. Create `hl7-listener/Dockerfile`

```dockerfile
# HL7 Listener — Cloud Run service
# Base: python:3.12-slim (TR-019: minimal attack surface)
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Cloud Run health probe port (HTTP)
EXPOSE 8080
# MLLP TCP port
EXPOSE 2575

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "app.main"]
```

---

## Validation

```bash
cd hl7-listener

# 1. Verify metrics module imports
python -c "from app.metrics import HL7_MESSAGES_TOTAL, HL7_ACK_LATENCY, ACTIVE_CONNECTIONS; print('metrics.py: OK')"

# 2. Verify health server imports
python -c "from app.health import start_health_server; print('health.py: OK')"

# 3. Start the health server in background and probe it (requires httpx or curl)
python -c "
import asyncio
from app.health import start_health_server

async def test():
    server_task = asyncio.create_task(start_health_server(port=18080))
    await asyncio.sleep(0.2)
    reader, writer = await asyncio.open_connection('127.0.0.1', 18080)
    writer.write(b'GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n')
    await writer.drain()
    data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    writer.close()
    server_task.cancel()
    assert b'200' in data, f'Unexpected response: {data}'
    print('Health probe: OK')

asyncio.run(test())
"
```

---

## Definition of Done Checklist

- [ ] `hl7-listener/app/metrics.py` created with `HL7_MESSAGES_TOTAL` (Counter), `HL7_ACK_LATENCY` (Histogram), `ACTIVE_CONNECTIONS` (Gauge)
- [ ] `SO_KEEPALIVE` set on each accepted MLLP socket; `TCP_KEEPIDLE=30`, `TCP_KEEPINTVL=10`, `TCP_KEEPCNT=3` set with `hasattr` guards
- [ ] `hl7-listener/app/health.py` created with `start_health_server(host, port)` coroutine
- [ ] `GET /health` → `200 OK` | `GET /ready` → `200 OK` | `GET /metrics` → Prometheus text
- [ ] `hl7-listener/Dockerfile` created using `python:3.12-slim` base image
- [ ] All three validation commands pass
