---
task_id: task_004
story_id: us_003
epic: EP-TECH
title: OpenTelemetry Python Instrumentation — Distributed Traces Across All Services
layer: Observability / Application
effort_hours: 2
sequence: 4
status: Draft
---

# TASK-004: OpenTelemetry Python Instrumentation — Distributed Traces Across All Services

> **Story:** EP-TECH/US-003 | **Layer:** Observability / Application | **Effort:** 2 hours | **Seq:** 4 of 4

## Objective

Instrument all Python FastAPI and agent services with OpenTelemetry so that `X-Cloud-Trace-Context` headers are propagated across service boundaries, producing end-to-end distributed traces visible in Cloud Trace — satisfying AC-8.

## Implementation Steps

### 1. Shared OpenTelemetry Package (`services/shared/otel.py`)

Create a shared library imported by all services:

```python
"""
services/shared/otel.py
Centralised OpenTelemetry configuration for all SmartHandoff Python services.
Import and call setup_telemetry() at application startup.
"""
import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.cloud_trace_propagator import CloudTraceFormatPropagator

logger = logging.getLogger(__name__)


def setup_telemetry(
    service_name: str,
    app=None,          # FastAPI app instance (optional — agents don't have one)
    engine=None,       # SQLAlchemy engine (optional)
    sample_rate: float = 1.0,  # 100% sampling by default; reduce in prod if needed
) -> trace.Tracer:
    """
    Configure OpenTelemetry with Google Cloud Trace exporter.

    Call this at application startup, before any request handling begins.

    Args:
        service_name: Service identifier (e.g. 'api-gateway', 'docs-agent')
        app: FastAPI application instance for automatic HTTP instrumentation
        engine: SQLAlchemy engine for automatic DB query tracing
        sample_rate: Fraction of traces to sample (0.0-1.0)

    Returns:
        Configured tracer instance
    """
    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set — Cloud Trace export disabled")
        return trace.get_tracer(service_name)

    # Use Google Cloud Trace propagator for X-Cloud-Trace-Context header
    set_global_textmap(CloudTraceFormatPropagator())

    # Configure tracer provider with Cloud Trace exporter
    exporter = CloudTraceSpanExporter(project_id=project_id)
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer(service_name)

    # Auto-instrument FastAPI (adds spans for all HTTP requests/responses)
    if app is not None:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls="health,ready,metrics",  # Don't trace health probes
        )
        logger.info(f"FastAPI auto-instrumentation enabled for {service_name}")

    # Auto-instrument outbound HTTP calls (FHIR client, Vertex AI, etc.)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    # Auto-instrument SQLAlchemy (traces every DB query — disable in high-volume prod)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            tracer_provider=provider,
            enable_commenter=True,  # Adds sqlcommenter tags to queries
        )
        logger.info(f"SQLAlchemy auto-instrumentation enabled for {service_name}")

    logger.info(
        f"OpenTelemetry configured for '{service_name}' "
        f"(project={project_id}, sample_rate={sample_rate})"
    )
    return tracer
```

### 2. FastAPI Service Integration (`services/api-gateway/src/main.py`)

```python
from fastapi import FastAPI
from services.shared.otel import setup_telemetry
from src.db import engine  # SQLAlchemy engine

app = FastAPI(title="SmartHandoff API Gateway")

# Initialise OpenTelemetry BEFORE any route handlers are registered
tracer = setup_telemetry(
    service_name="api-gateway",
    app=app,
    engine=engine,
)

# --- Routes registered after OTel setup ---
from src.routers import auth, encounters, patients, documents, beds, analytics, admin
app.include_router(auth.router)
app.include_router(encounters.router)
# ... etc
```

### 3. Agent Service Integration (`services/coordinator-agent/src/main.py`)

Agent services don't have FastAPI apps — they run a Pub/Sub pull loop. Use manual spans:

```python
import asyncio
import logging
from opentelemetry import trace
from services.shared.otel import setup_telemetry
from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)
tracer = setup_telemetry(service_name="coordinator-agent")


async def process_adt_event(message: pubsub_v1.subscriber.message.Message) -> None:
    """Process a single ADT event with distributed tracing."""

    # Extract trace context from Pub/Sub message attributes (if present)
    from opentelemetry.propagate import extract
    carrier = dict(message.attributes)  # Pub/Sub message attributes carry trace context
    context = extract(carrier)

    with tracer.start_as_current_span(
        "coordinator.process_adt_event",
        context=context,
        kind=trace.SpanKind.CONSUMER,
    ) as span:
        span.set_attribute("messaging.system", "pubsub")
        span.set_attribute("messaging.destination", "adt-events")
        span.set_attribute("adt.event_type", message.attributes.get("event_type", "unknown"))
        span.set_attribute("adt.encounter_id", message.attributes.get("encounter_id", ""))

        try:
            # Parse and process the event
            event_data = json.loads(message.data.decode("utf-8"))
            await _dispatch_agent_tasks(event_data, span)
            message.ack()
            span.set_attribute("result", "success")
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            message.nack()
            raise


async def _dispatch_agent_tasks(event_data: dict, parent_span) -> None:
    """Dispatch tasks to all downstream agents."""
    with tracer.start_as_current_span(
        "coordinator.dispatch_tasks",
        context=trace.set_span_in_context(parent_span),
    ) as span:
        span.set_attribute("agent.count", 5)
        # ... task dispatch logic
```

### 4. Propagate Trace Context in Pub/Sub Messages

When publishing events to Pub/Sub, inject trace context into message attributes so downstream agents can continue the trace:

```python
# services/hl7-listener/src/publisher.py
from opentelemetry.propagate import inject
from google.cloud import pubsub_v1

def publish_adt_event(publisher: pubsub_v1.PublisherClient, topic: str, event: dict) -> str:
    """Publish an ADT event to Pub/Sub with trace context in message attributes."""
    data = json.dumps(event).encode("utf-8")

    # Inject current trace context into Pub/Sub message attributes
    attributes = {
        "event_type": event["event_type"],
        "encounter_id": event.get("encounter_id", ""),
    }
    inject(attributes)  # Adds 'X-Cloud-Trace-Context' to attributes dict

    future = publisher.publish(topic, data=data, **attributes)
    return future.result()
```

### 5. Requirements (`services/shared/requirements.txt`)

```text
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
opentelemetry-exporter-gcp-trace==1.6.0
opentelemetry-instrumentation-fastapi==0.46b0
opentelemetry-instrumentation-httpx==0.46b0
opentelemetry-instrumentation-sqlalchemy==0.46b0
opentelemetry-propagator-gcp==1.6.0
```

### 6. Verify Traces in Cloud Trace

```bash
# 1. Send a test ADT event through the full pipeline
curl -X POST https://api.staging.smarthandoff.health/api/v1/test/simulate-adt \
  -H "Authorization: Bearer $TEST_JWT" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "A01", "encounter_id": "test-123"}'

# 2. View traces in Cloud Trace (wait 30-60 seconds for export)
gcloud trace list --project=smarthandoff-staging \
  --filter='displayName:"coordinator.process_adt_event"' \
  --limit=5

# 3. Verify trace spans
TRACE_ID=$(gcloud trace list ... --format='value(traceId)' | head -1)
gcloud trace get "$TRACE_ID" --project=smarthandoff-staging
# Expected output: spans from hl7-listener → coordinator-agent → docs-agent (linked)
```

### 7. PHI Safety in Traces

Add a span sanitiser to strip PHI from trace attributes before export:

```python
# services/shared/otel_sanitiser.py
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.sdk.trace import ReadableSpan

PHI_ATTRIBUTE_KEYS = {"patient.name", "patient.dob", "patient.phone", "patient.email"}

class PHISanitiserSpanProcessor(SpanProcessor):
    """Remove PHI attributes from spans before export to Cloud Trace."""

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span: ReadableSpan):
        for key in PHI_ATTRIBUTE_KEYS:
            if key in span.attributes:
                # Replace PHI with a redacted marker
                span._attributes[key] = "[REDACTED]"

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000):
        pass
```

Register this before the Cloud Trace exporter in `setup_telemetry()`:

```python
provider.add_span_processor(PHISanitiserSpanProcessor())
provider.add_span_processor(BatchSpanProcessor(exporter))
```

## Acceptance Criteria

- [ ] **AC-8:** After sending a test ADT event: `gcloud trace list --project={PROJECT} --filter='displayName:*adt_event*'` returns at least 1 trace with spans from multiple services
- [ ] Trace in Cloud Console shows connected spans: `hl7-listener.publish` → `coordinator-agent.process_adt_event` → `coordinator-agent.dispatch_tasks` with correct parent-child relationships
- [ ] `X-Cloud-Trace-Context` header propagated: API Gateway FastAPI response headers include `X-Cloud-Trace-Context` — confirmed via `curl -I https://api.staging.../health`
- [ ] PHI sanitiser active: trace span attributes do NOT contain `patient.name`, `patient.dob`, etc. — confirmed by inspecting span details in Cloud Trace console
- [ ] `HTTPXClientInstrumentor` active: FHIR client HTTP calls appear as child spans within agent trace spans
- [ ] SQLAlchemy instrumentation active: DB queries appear as child spans with SQL text (non-PHI queries only) in API Gateway traces

## Files to Create

```
services/shared/otel.py
services/shared/otel_sanitiser.py
services/shared/requirements.txt
services/api-gateway/src/main.py           (update to call setup_telemetry)
services/coordinator-agent/src/main.py     (update to use tracer)
services/hl7-listener/src/publisher.py     (update to inject trace context)
```

## Notes

- `BatchSpanProcessor` is used (not `SimpleSpanProcessor`) — batching reduces the number of API calls to Cloud Trace and prevents request latency impact from synchronous trace export
- `excluded_urls="health,ready,metrics"` prevents health probe spans from polluting the trace feed with thousands of low-value entries
- The PHI sanitiser processor runs **before** the Cloud Trace exporter in the processor chain — this is the correct ordering; reversed order would export PHI and then strip it from the local span (too late)
- Cloud Trace has a 30-60 second ingestion delay; traces won't appear immediately after the first instrumented request
- `trace_id` is a 32-character hex string; Cloud Run automatically propagates it via `X-Cloud-Trace-Context` if the service is behind the Google Load Balancer — the OTel setup ensures it's also propagated across Pub/Sub message boundaries
