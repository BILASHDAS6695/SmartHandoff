"""Care Team Escalation module (US-045).

Components:
    - schemas.py: Pydantic models for escalation data
    - models.py: SQLAlchemy ORM model (ChatbotEscalation)
    - service.py: Business logic for escalation creation and acknowledgement
    - pubsub_publisher.py: Pub/Sub integration for notification dispatch
    - oncall_resolver.py: On-call nurse lookup logic
    - monitoring.py: SLA metric emission
"""
from backend.app.agents.patient_comm.escalation.models import ChatbotEscalation
from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationAcknowledge,
    EscalationAlertPayload,
    EscalationConfirmedMessage,
    EscalationCreate,
    EscalationMessageType,
    EscalationRead,
    NotificationChannel,
)

__all__ = [
    "ChatbotEscalation",
    "EscalationCreate",
    "EscalationRead",
    "EscalationAcknowledge",
    "EscalationAlertPayload",
    "EscalationConfirmedMessage",
    "NotificationChannel",
    "EscalationMessageType",
]
