"""
services/shared/otel/middleware.py

Starlette/FastAPI ASGI middleware that extracts incoming W3C Trace Context /
Cloud Trace headers and starts a root server span for each HTTP request.

Usage:
    from shared.otel.middleware import TraceMiddleware
    app.add_middleware(TraceMiddleware)   # register before other middleware

The middleware works in conjunction with ``opentelemetry-instrumentation-fastapi``
which creates per-route child spans.  Adding both gives the full span hierarchy:

    [TraceMiddleware root span]
      └─ [FastAPIInstrumentor route span]
           └─ [application code child spans via get_tracer(__name__)]
"""
from __future__ import annotations

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TraceMiddleware(BaseHTTPMiddleware):
    """
    Extracts distributed trace context from incoming request headers and
    attaches it to the current OpenTelemetry context for the request lifetime.

    Adds ``X-Trace-Id`` to every response so callers can correlate requests
    with Cloud Trace without accessing the Cloud Console.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract W3C traceparent / Cloud Trace X-Cloud-Trace-Context header
        carrier = dict(request.headers)
        ctx = extract(carrier)
        token = otel_context.attach(ctx)

        tracer = trace.get_tracer(__name__)
        span_name = f"{request.method} {request.url.path}"

        try:
            with tracer.start_as_current_span(
                span_name,
                kind=trace.SpanKind.SERVER,
            ) as span:
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute("http.scheme", request.url.scheme)
                span.set_attribute("http.host", request.url.hostname or "")
                span.set_attribute("http.target", request.url.path)

                response = await call_next(request)

                span.set_attribute("http.status_code", response.status_code)

                # Expose trace ID in response header for client-side correlation
                span_ctx = span.get_span_context()
                if span_ctx.is_valid:
                    response.headers["X-Trace-Id"] = f"{span_ctx.trace_id:032x}"

                return response
        finally:
            otel_context.detach(token)
