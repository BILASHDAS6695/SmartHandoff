---
id: TASK-006
title: "Create Shared OpenTelemetry Python Library with Cloud Trace Exporter"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: Application
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: []
---

# TASK-006: Create Shared OpenTelemetry Python Library with Cloud Trace Exporter

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Application | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-004 Acceptance Criterion 2 (Scenario 2) requires a single end-to-end trace in Cloud Trace spanning all 10 services — from MLLP receipt through coordinator to SignalR push — with correct parent-child span relationships and latency breakdown.

The Technical Notes specify: *"Use `opentelemetry-sdk` Python package with `google-cloud-trace` exporter"*.

Rather than duplicating OTel initialisation across all 10 services, this task creates a **shared Python library** (`services/shared/otel/`) that every service imports. This single initialisation point ensures consistent tracer configuration, propagator setup, and exporter configuration across the entire platform. TASK-008 wires each service to call this library.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 2** | OTel configured across all 10 services; single trace shows every span with correct parent-child relationships |

---

## Implementation Steps

### 1. Create `services/shared/otel/__init__.py`

```python
"""Shared OpenTelemetry initialisation library for SmartHandoff services."""
from .setup import init_tracer, get_tracer

__all__ = ["init_tracer", "get_tracer"]
```

### 2. Create `services/shared/otel/setup.py`

```python
"""
OpenTelemetry tracer factory with Google Cloud Trace exporter.

Usage in each service's main.py:
    from shared.otel import init_tracer
    init_tracer(service_name="api-gateway")
"""
import os
import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.cloud_trace_propagator import CloudTraceFormatPropagator

logger = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None


def init_tracer(service_name: str, service_version: str = "1.0.0") -> trace.Tracer:
    """
    Initialise a TracerProvider with the Google Cloud Trace exporter and
    register it as the global OpenTelemetry tracer.

    Call once at application startup, before any request handling begins.

    Args:
        service_name: Cloud Run service name (e.g. "api-gateway"). Used as
                      the ``service.name`` resource attribute in Cloud Trace.
        service_version: Semantic version string for the service.

    Returns:
        A ``trace.Tracer`` instance scoped to ``service_name``.
    """
    global _tracer

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        logger.warning(
            "GOOGLE_CLOUD_PROJECT not set — Cloud Trace exporter will be disabled. "
            "Traces will only be emitted to console."
        )

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
        "deployment.environment": os.environ.get("ENVIRONMENT", "dev"),
        "cloud.provider": "gcp",
        "cloud.platform": "gcp_cloud_run",
    })

    provider = TracerProvider(resource=resource)

    if project_id:
        exporter = CloudTraceSpanExporter(project_id=project_id)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "Cloud Trace exporter registered for project=%s service=%s",
            project_id,
            service_name,
        )
    else:
        # Local dev fallback: emit spans to stdout for debugging
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Register as global provider so instrumentation libraries pick it up
    trace.set_tracer_provider(provider)

    # Use Cloud Trace propagation format for X-Cloud-Trace-Context header
    # This ensures parent-child span relationships survive HTTP hops between services
    set_global_textmap(CloudTraceFormatPropagator())

    _tracer = trace.get_tracer(service_name, service_version)
    return _tracer


def get_tracer() -> trace.Tracer:
    """
    Return the global tracer. Must be called after ``init_tracer()``.

    Raises:
        RuntimeError: If ``init_tracer()`` has not been called yet.
    """
    if _tracer is None:
        raise RuntimeError(
            "get_tracer() called before init_tracer(). "
            "Call init_tracer(service_name) once at application startup."
        )
    return _tracer
```

### 3. Create `services/shared/otel/middleware.py`

FastAPI middleware that automatically creates a root span for each incoming HTTP request, extracting the upstream trace context from the `X-Cloud-Trace-Context` header:

```python
"""
FastAPI middleware that creates a root HTTP span for each incoming request,
propagating trace context from upstream callers via X-Cloud-Trace-Context.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from opentelemetry import trace, context
from opentelemetry.propagate import extract


class TraceMiddleware(BaseHTTPMiddleware):
    """Attach an OpenTelemetry span to every incoming HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract upstream trace context from request headers
        ctx = extract(dict(request.headers))
        token = context.attach(ctx)

        tracer = trace.get_tracer(__name__)
        span_name = f"{request.method} {request.url.path}"

        with tracer.start_as_current_span(
            span_name,
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", request.url.path)

            response = await call_next(request)

            span.set_attribute("http.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(trace.Status(trace.StatusCode.ERROR))

        context.detach(token)
        return response
```

### 4. Create `services/shared/otel/requirements.txt`

Pin the OTel packages used by the shared library. Each service's `requirements.txt` includes this file via `-r shared/otel/requirements.txt`:

```text
opentelemetry-sdk==1.24.0
opentelemetry-api==1.24.0
opentelemetry-exporter-gcp-trace==1.6.0
opentelemetry-propagator-gcp==1.6.0
opentelemetry-instrumentation-fastapi==0.45b0
opentelemetry-instrumentation-requests==0.45b0
opentelemetry-instrumentation-sqlalchemy==0.45b0
```

> **Version pinning note:** Pin exact versions to prevent OTel SDK API breakages. Update all services in lockstep when upgrading.

---

## Files Changed

| File | Action |
|---|---|
| `services/shared/otel/__init__.py` | Create |
| `services/shared/otel/setup.py` | Create |
| `services/shared/otel/middleware.py` | Create |
| `services/shared/otel/requirements.txt` | Create |

---

## Definition of Done

- [ ] `services/shared/otel/` directory contains all four files
- [ ] `init_tracer("test-service")` executes without error when `GOOGLE_CLOUD_PROJECT` is unset (falls back to `ConsoleSpanExporter`)
- [ ] `TraceMiddleware` correctly propagates `X-Cloud-Trace-Context` header to child spans in unit tests
- [ ] `get_tracer()` raises `RuntimeError` when called before `init_tracer()` — verified by unit test
- [ ] All OTel packages pinned to exact versions in `requirements.txt`
