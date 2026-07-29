"""Cloud Monitoring metric emission for escalation SLA tracking (US-045).

Design ref:
    design.md §10.1 — Cloud Monitoring custom metrics
    US-045 AC Scenario 2 / DoD — if >2 min, flag for review (log metric only in Phase 1)
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Metric name registered in Cloud Monitoring
_METRIC_ESCALATION_SLA_BREACH = "escalation_sla_breach"
_METRIC_ESCALATION_ACKNOWLEDGED = "escalation_acknowledged"

# SLA threshold in minutes (US-045 FR-062)
SLA_THRESHOLD_MINUTES: float = 2.0


def _ack_time_bucket(minutes: float) -> str:
    """Categorise acknowledgement time into a label bucket for Cloud Monitoring."""
    if minutes <= 2.0:
        return "0-2min"
    if minutes <= 5.0:
        return "2-5min"
    return "5+min"


def emit_acknowledgement_metric(
    encounter_id: str,
    escalation_id: str,
    ack_time_minutes: float,
) -> None:
    """Emit Cloud Monitoring metric for escalation acknowledgement.

    Emits:
        - 'escalation_acknowledged' always (for SLA distribution dashboard)
        - 'escalation_sla_breach' if ack_time_minutes > SLA_THRESHOLD_MINUTES

    Phase 1: Implemented via structured log entry that Cloud Monitoring
    log-based metrics can pick up. A dedicated Cloud Monitoring metric
    descriptor is provisioned by Terraform (infra/modules/monitoring/).
    """
    bucket = _ack_time_bucket(ack_time_minutes)

    log.info(
        _METRIC_ESCALATION_ACKNOWLEDGED,
        extra={
            "metric": _METRIC_ESCALATION_ACKNOWLEDGED,
            "encounter_id": encounter_id,
            "escalation_id": escalation_id,
            "ack_time_minutes": ack_time_minutes,
            "ack_time_bucket": bucket,
        },
    )

    if ack_time_minutes > SLA_THRESHOLD_MINUTES:
        log.warning(
            _METRIC_ESCALATION_SLA_BREACH,
            extra={
                "metric": _METRIC_ESCALATION_SLA_BREACH,
                "encounter_id": encounter_id,
                "escalation_id": escalation_id,
                "ack_time_minutes": ack_time_minutes,
                "ack_time_bucket": bucket,
            },
        )
