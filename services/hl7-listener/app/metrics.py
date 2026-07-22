"""Prometheus metrics for the HL7 Listener service.

Exposes three metrics consumed by Cloud Monitoring (GCP Prometheus scrape):

  hl7_messages_total{status}  — Counter; status values:
                                  "ack" | "nack_parse_error" | "nack_timeout" | "nack_oversized"
  hl7_ack_latency_ms          — Histogram; ACK round-trip latency in milliseconds
  hl7_active_connections      — Gauge; current number of active MLLP TCP connections

The /metrics HTTP endpoint is served by the health server (health.py) on port 8080
alongside /health and /ready.

Design refs:
    US-011 DoD — Prometheus metrics: hl7_messages_total, hl7_ack_latency_ms, hl7_active_connections
    TR-016     — Health probes / observability
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HL7_MESSAGES_TOTAL: Counter = Counter(
    name="hl7_messages_total",
    documentation=(
        "Total HL7 messages processed, labelled by outcome status. "
        "status values: ack | nack_parse_error | nack_timeout | nack_oversized"
    ),
    labelnames=["status"],
)

HL7_ACK_LATENCY: Histogram = Histogram(
    name="hl7_ack_latency_ms",
    documentation=(
        "End-to-end ACK latency in milliseconds, measured from TCP payload receipt "
        "to ACK bytes written to socket. SLA target: <200ms (AIR-001)."
    ),
    buckets=[10, 25, 50, 100, 150, 200, 250, 500, 1000],
)

ACTIVE_CONNECTIONS: Gauge = Gauge(
    name="hl7_active_connections",
    documentation="Current number of active MLLP TCP connections.",
)
