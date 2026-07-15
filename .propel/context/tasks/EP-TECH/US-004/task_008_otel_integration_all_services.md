---
id: TASK-008
title: "Integrate OpenTelemetry SDK and Structured Logging into All 10 Services"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: Application
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-006, TASK-007]
---

# TASK-008: Integrate OpenTelemetry SDK and Structured Logging into All 10 Services

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Application | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

TASK-006 created the shared OTel library and TASK-007 created the shared logging library. This task wires both into every Cloud Run service by applying a **uniform startup pattern** to each service's entry point (`main.py`). The integration must produce a single distributed trace in Cloud Trace with correct parent-child spans from MLLP receipt → coordinator → documentation agent (Scenario 2 AC).

Each service requires:
1. `init_tracer(service_name)` called before the ASGI server starts.
2. `configure_logging(service_name)` called immediately after.
3. `TraceMiddleware` added to the FastAPI application (for HTTP services).
4. `opentelemetry-instrumentation-fastapi` auto-instrumentation wired at startup.
5. OTel packages added to each service's `requirements.txt`.

The HL7 Listener (non-HTTP, MLLP TCP) receives special treatment — it creates spans manually rather than using the FastAPI middleware.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 2** | OTel configured across all 10 services; single trace spans MLLP receipt to SignalR push |
| **Scenario 4** | PHI redaction middleware active in all services |

---

## Implementation Steps

### 1. Standard Integration Pattern — HTTP Services (9 of 10)

Apply the following pattern to each of the 9 HTTP services:
`api-gateway`, `coordinator-agent`, `docs-agent`, `medrecon-agent`, `bed-management-agent`, `followup-care-agent`, `patient-comms-agent`, `ml-inference`, `notification-svc`.

**In `services/<service-name>/main.py`** — add to the top of the file before FastAPI `app` creation:

```python
import os
from shared.otel import init_tracer
from shared.logging import configure_logging
from shared.otel.middleware import TraceMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# ── Observability bootstrap ───────────────────────────────────────────────────
SERVICE_NAME = os.environ.get("K_SERVICE", "<service-name>")  # Cloud Run injects K_SERVICE
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="SmartHandoff <ServiceName>")

# Register OTel middleware before any other middleware
app.add_middleware(TraceMiddleware)

# Auto-instrument FastAPI routes (creates child spans per endpoint)
FastAPIInstrumentor.instrument_app(app)
```

**Service-specific `SERVICE_NAME` constants:**

| Service | `SERVICE_NAME` constant |
|---|---|
| `api-gateway` | `"api-gateway"` |
| `coordinator-agent` | `"coordinator-agent"` |
| `docs-agent` | `"docs-agent"` |
| `medrecon-agent` | `"medrecon-agent"` |
| `bed-management-agent` | `"bed-management-agent"` |
| `followup-care-agent` | `"followup-care-agent"` |
| `patient-comms-agent` | `"patient-comms-agent"` |
| `ml-inference` | `"ml-inference"` |
| `notification-svc` | `"notification-svc"` |

### 2. HL7 Listener — MLLP Manual Span Instrumentation

The `hl7-listener` service is not a FastAPI application — it runs an MLLP TCP server. Add manual span creation around the MLLP message processing loop.

**In `services/hl7-listener/main.py`:**

```python
import os
from shared.otel import init_tracer, get_tracer
from shared.logging import configure_logging

SERVICE_NAME = os.environ.get("K_SERVICE", "hl7-listener")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)
```

**In `services/hl7-listener/mllp_handler.py`** — wrap each ADT message processing with a root span:

```python
from opentelemetry import trace
from opentelemetry.propagate import inject
from shared.otel import get_tracer
import logging

logger = logging.getLogger(__name__)


def handle_adt_message(raw_hl7: bytes, pubsub_client) -> None:
    """Process a single MLLP ADT message and publish to Pub/Sub."""
    tracer = get_tracer()

    with tracer.start_as_current_span(
        "hl7-listener.process_adt_message",
        kind=trace.SpanKind.SERVER,
    ) as span:
        # Inject trace context into Pub/Sub message attributes so downstream
        # agents can continue the trace as child spans
        carrier: dict[str, str] = {}
        inject(carrier)

        message_data = _parse_hl7(raw_hl7)
        span.set_attribute("hl7.message_type", message_data.get("message_type", "unknown"))
        span.set_attribute("hl7.event_type", message_data.get("event_type", "unknown"))

        pubsub_client.publish(
            topic=os.environ["PUBSUB_TOPIC"],
            data=message_data["payload"],
            # Pass trace context as Pub/Sub message attributes
            **{f"traceparent": carrier.get("traceparent", "")},
            **{f"tracestate": carrier.get("tracestate", "")},
        )
        logger.info("ADT message published to Pub/Sub", extra={"event_type": message_data.get("event_type")})
```

### 3. Pub/Sub Consumer Services — Extract Trace Context from Message Attributes

Agent services (coordinator-agent, docs-agent, medrecon-agent, etc.) that consume Pub/Sub messages must **extract** the trace context from message attributes to continue the distributed trace as child spans.

**In each agent's Pub/Sub message handler:**

```python
from opentelemetry.propagate import extract
from opentelemetry import trace, context

def process_pubsub_message(message: pubsub_v1.types.ReceivedMessage) -> None:
    tracer = trace.get_tracer(__name__)

    # Extract upstream trace context from Pub/Sub message attributes
    carrier = {
        "traceparent": message.message.attributes.get("traceparent", ""),
        "tracestate":  message.message.attributes.get("tracestate", ""),
    }
    ctx = extract(carrier)
    token = context.attach(ctx)

    with tracer.start_as_current_span(
        f"{SERVICE_NAME}.process_adt_event",
        kind=trace.SpanKind.CONSUMER,
    ) as span:
        span.set_attribute("messaging.system", "pubsub")
        span.set_attribute("messaging.destination", message.subscription)
        # ... agent processing logic ...

    context.detach(token)
```

### 4. Add OTel Packages to Each Service's `requirements.txt`

In each service's `requirements.txt`, add a reference to the shared OTel requirements:

```text
-r ../shared/otel/requirements.txt
```

---

## Files Changed

| File | Action |
|---|---|
| `services/api-gateway/main.py` | Add `init_tracer`, `configure_logging`, `TraceMiddleware`, `FastAPIInstrumentor` |
| `services/coordinator-agent/main.py` | Add OTel bootstrap + Pub/Sub context extraction |
| `services/docs-agent/main.py` | Add OTel bootstrap + Pub/Sub context extraction |
| `services/medrecon-agent/main.py` | Add OTel bootstrap + Pub/Sub context extraction |
| `services/bed-management-agent/main.py` | Add OTel bootstrap + Pub/Sub context extraction |
| `services/followup-care-agent/main.py` | Add OTel bootstrap + Pub/Sub context extraction |
| `services/patient-comms-agent/main.py` | Add OTel bootstrap + Pub/Sub context extraction |
| `services/ml-inference/main.py` | Add OTel bootstrap + `TraceMiddleware` |
| `services/notification-svc/main.py` | Add OTel bootstrap + `TraceMiddleware` |
| `services/hl7-listener/main.py` | Add OTel bootstrap |
| `services/hl7-listener/mllp_handler.py` | Manual span + trace context injection into Pub/Sub attributes |
| `services/*/requirements.txt` (10 files) | Add `-r ../shared/otel/requirements.txt` |

---

## Definition of Done

- [ ] All 10 services call `init_tracer()` and `configure_logging()` before first request/message processing
- [ ] All 9 HTTP services have `TraceMiddleware` registered and `FastAPIInstrumentor` wired
- [ ] HL7 Listener injects trace context (`traceparent`) into Pub/Sub message attributes
- [ ] All Pub/Sub consumer agents extract trace context from message attributes and create child spans
- [ ] Log output from each service is valid JSON when tested locally with `GOOGLE_CLOUD_PROJECT` unset
- [ ] OTel packages version-pinned in all 10 `requirements.txt` files via shared `requirements.txt` reference
