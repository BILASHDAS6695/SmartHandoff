"""
services/bed-management-agent/main.py

Bed Management Agent Cloud Run service entry point.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shared.otel import init_tracer
from shared.logging import configure_logging
from shared.otel.middleware import TraceMiddleware

SERVICE_NAME = os.environ.get("K_SERVICE", "bed-management-agent")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)

app = FastAPI(title="SmartHandoff Bed Management Agent")
app.add_middleware(TraceMiddleware)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Cloud Run health probe endpoint — must return HTTP 200."""
    return {"status": "ok", "service": SERVICE_NAME}

# ── Pub/Sub context propagation: see coordinator-agent/main.py for pattern ──
