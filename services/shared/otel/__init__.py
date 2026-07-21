"""
services/shared/otel/__init__.py

Public API for the shared OpenTelemetry instrumentation library.
Import ``init_tracer`` and ``get_tracer`` from this package.
"""
from .setup import get_tracer, init_tracer

__all__ = ["init_tracer", "get_tracer"]
