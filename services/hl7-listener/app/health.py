"""Minimal asyncio HTTP server exposing /health, /ready, and /metrics endpoints.

Runs on port 8080 in the same asyncio event loop as the MLLP TCP server (main.py).
Cloud Run health probes (TR-016):
  - Liveness:   GET /health  → 200 OK
  - Readiness:  GET /ready   → 200 OK
  - Metrics:    GET /metrics → 200 OK (Prometheus text format)

The server uses only stdlib asyncio — no external HTTP framework dependency.
This keeps the container image lean and startup time under 1 second.

Design refs:
    TR-016   — Health check: GET /health every 10s, GET /ready every 5s
    US-011   — DoD: GET /health and GET /ready as asyncio HTTP server
"""
from __future__ import annotations

import asyncio
import logging

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = logging.getLogger(__name__)

_HTTP_200_PLAIN = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK"
_HTTP_404 = b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNot found"


async def _handle_http(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single HTTP request from the Cloud Run health probe."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        request_str = request_line.decode("ascii", errors="replace").strip()

        # Consume remaining headers (not needed for health checks)
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not line or line == b"\r\n":
                break

        # Parse method and path from "GET /health HTTP/1.1"
        parts = request_str.split()
        path = parts[1] if len(parts) >= 2 else "/"

        if path in ("/health", "/ready"):
            writer.write(_HTTP_200_PLAIN)
            logger.debug("health_probe_ok path=%s", path)

        elif path == "/metrics":
            metrics_bytes = generate_latest()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: " + CONTENT_TYPE_LATEST.encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + metrics_bytes
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
