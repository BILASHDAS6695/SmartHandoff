"""
services/shared/otel/setup.py

Initialises the OpenTelemetry SDK with a Cloud Trace exporter for every
SmartHandoff Cloud Run service.

Usage (called once at application startup, before FastAPI ``app`` creation):

    from shared.otel import init_tracer, get_tracer
    init_tracer(service_name="api-gateway")
    tracer = get_tracer(__name__)
"""
from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

_INITIALIZED = False


def init_tracer(service_name: str, service_version: str = "1.0.0") -> None:
    """
    Initialise the global OpenTelemetry TracerProvider.

    Configures Cloud Trace exporter when ``GOOGLE_CLOUD_PROJECT`` is set
    (i.e. running on Cloud Run).  Falls back to stdout span logging for
    local development when the env var is absent.

    Idempotent — calling multiple times has no effect after the first call.

    Args:
        service_name:    Logical service identifier (e.g. ``"api-gateway"``).
        service_version: Semver string injected into span resources.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.environ.get("ENVIRONMENT", "dev"),
            "cloud.provider": "gcp",
            "cloud.platform": "gcp_cloud_run",
        }
    )

    provider = TracerProvider(resource=resource)

    if project_id:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.propagators.cloud_trace_propagator import (
            CloudTraceFormatPropagator,
        )

        exporter = CloudTraceSpanExporter(project_id=project_id)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        set_global_textmap(CloudTraceFormatPropagator())
        logger.info(
            "Cloud Trace exporter registered for project=%s service=%s",
            project_id,
            service_name,
        )
    else:
        # Local development: emit spans to stdout for debugging
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info(
            "Cloud Trace project not set — using ConsoleSpanExporter (local dev)"
        )

    trace.set_tracer_provider(provider)
    _INITIALIZED = True


def get_tracer(name: str) -> trace.Tracer:
    """
    Return a named tracer from the global provider.

    Call ``init_tracer()`` before this function.  If called before
    ``init_tracer()``, returns a no-op tracer.

    Args:
        name: Typically ``__name__`` of the calling module.
    """
    return trace.get_tracer(name)
