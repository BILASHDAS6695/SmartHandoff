"""
services/portal-bff/main.py

Portal BFF (Backend for Frontend) Cloud Run service entry point.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shared.otel import init_tracer
from shared.logging import configure_logging
from shared.otel.middleware import TraceMiddleware

SERVICE_NAME = os.environ.get("K_SERVICE", "portal-bff")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)

app = FastAPI(title="SmartHandoff Portal BFF")
app.add_middleware(TraceMiddleware)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}
