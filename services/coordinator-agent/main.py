"""
services/coordinator-agent/main.py

Coordinator Agent Cloud Run service entry point.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shared.otel import init_tracer
from shared.logging import configure_logging
from shared.otel.middleware import TraceMiddleware

SERVICE_NAME = os.environ.get("K_SERVICE", "coordinator-agent")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)

app = FastAPI(title="SmartHandoff Coordinator Agent")
app.add_middleware(TraceMiddleware)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


# ── Pub/Sub context propagation helper ───────────────────────────────────────
# Use the pattern below in any Pub/Sub message handler to continue distributed
# traces received from hl7-listener or other upstream publishers:
#
#   from opentelemetry.propagate import extract
#   from opentelemetry import trace, context as otel_context
#
#   carrier = {
#       "traceparent": message.message.attributes.get("traceparent", ""),
#       "tracestate":  message.message.attributes.get("tracestate", ""),
#   }
#   ctx = extract(carrier)
#   token = otel_context.attach(ctx)
#   with trace.get_tracer(__name__).start_as_current_span(
#       "coordinator-agent.process_adt_event", kind=trace.SpanKind.CONSUMER
#   ) as span:
#       span.set_attribute("messaging.system", "pubsub")
#       # ... agent logic ...
#   otel_context.detach(token)
