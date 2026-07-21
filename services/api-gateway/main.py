"""
services/api-gateway/main.py

API Gateway Cloud Run service entry point.

Observability is bootstrapped via the shared OTel and structured logging
libraries (EP-TECH / US-004 / TASK-006, TASK-007) before the FastAPI
application is instantiated.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shared.otel import init_tracer
from shared.logging import configure_logging
from shared.otel.middleware import TraceMiddleware

# ── Observability bootstrap (must run before app creation) ───────────────────
# Cloud Run injects K_SERVICE with the deployed service name.
SERVICE_NAME = os.environ.get("K_SERVICE", "api-gateway")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="SmartHandoff API Gateway")

# Register OTel middleware before any other middleware so the trace context
# is established before route handlers execute.
app.add_middleware(TraceMiddleware)

# Auto-instrument all FastAPI route handlers (creates per-endpoint child spans).
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Cloud Run health probe endpoint — must return HTTP 200."""
    return {"status": "ok", "service": SERVICE_NAME}
