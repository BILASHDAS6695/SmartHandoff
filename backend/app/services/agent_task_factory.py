"""AgentTaskFactory — creates AgentTask rows from ADT events and encounter state.

Design refs:
    US-020/US-021 — Agent task lifecycle and SLA thresholds
    US-019        — BLOCKED status for unresolved/ambiguous patients
    US-048        — Real-time task updates broadcast after creation
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.config.sla_loader import load_sla_config
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter, EncounterStatus


# Map HL7 ADT event type → agent types that should be triggered.
# Cancellation events (A11/A12/A13) intentionally map to an empty tuple —
# task cancellation is handled by CancellationService, not this factory.
ADT_EVENT_AGENT_MAP: dict[str, tuple[str, ...]] = {
    "A01": ("documentation", "medication_reconciliation", "bed_management"),
    "A02": ("bed_management", "coordinator"),
    "A03": (
        "documentation",
        "medication_reconciliation",
        "follow_up_care",
        "patient_communication",
    ),
    "A04": ("coordinator", "patient_communication"),
    "A08": ("coordinator",),
    "A11": (),
    "A12": (),
    "A13": (),
}

# Fallback mapping when no explicit ADT event type is provided.
ENCOUNTER_STATUS_AGENT_MAP: dict[str, tuple[str, ...]] = {
    EncounterStatus.REGISTERED.value: ("coordinator", "patient_communication"),
    EncounterStatus.PRE_ADMISSION.value: ("coordinator", "patient_communication"),
    EncounterStatus.ADMITTED.value: ("documentation", "medication_reconciliation", "bed_management"),
    EncounterStatus.TRANSFERRED.value: ("bed_management", "coordinator"),
    EncounterStatus.DISCHARGED.value: (
        "documentation",
        "medication_reconciliation",
        "follow_up_care",
        "patient_communication",
    ),
}

# Map agent type → default target clinical role for SignalR routing.
AGENT_ROLE_MAP: dict[str, str] = {
    "coordinator": "case_manager",
    "documentation": "physician",
    "medication_reconciliation": "pharmacist",
    "bed_management": "nurse",
    "follow_up_care": "case_manager",
    "patient_communication": "nurse",
}


class AgentTaskFactory:
    """Builds AgentTask ORM instances for an encounter based on ADT event type."""

    def __init__(self) -> None:
        self._sla_config = load_sla_config()

    def create_tasks_for_adt_event(
        self,
        encounter: Encounter,
        event_type: str | None,
        blocked: bool = False,
        blocked_reason: str | None = None,
    ) -> list[AgentTask]:
        """Return AgentTask instances to create for the given encounter + ADT event.

        Args:
            encounter: The encounter that received the ADT event.
            event_type: HL7 ADT event type (e.g. A01, A03). Falls back to encounter status.
            blocked: If True, tasks are created in BLOCKED status.
            blocked_reason: Human-readable reason when blocked=True.

        Returns:
            List of new AgentTask instances (not yet persisted).
        """
        agent_types = self._resolve_agent_types(event_type, encounter.status)
        status = (
            AgentTaskStatus.BLOCKED.value
            if blocked
            else AgentTaskStatus.PENDING.value
        )
        unit_id = encounter.unit or "unknown"
        now = datetime.now(timezone.utc)

        tasks: list[AgentTask] = []
        for agent_type in agent_types:
            threshold = self._sla_config.threshold_for(agent_type.upper())
            task = AgentTask(
                encounter_id=encounter.id,
                agent_type=agent_type,
                status=status,
                unit_id=unit_id,
                target_role=AGENT_ROLE_MAP.get(agent_type, "unassigned"),
                sla_threshold_minutes=threshold,
                sla_breached=False,
                blocked_reason=blocked_reason if blocked else None,
                started_at=now if not blocked else None,
            )
            tasks.append(task)
        return tasks

    def _resolve_agent_types(
        self, event_type: str | None, encounter_status: str
    ) -> Iterable[str]:
        """Pick agent types from ADT event type first, then encounter status."""
        if event_type:
            event_type = event_type.upper()
            if event_type in ADT_EVENT_AGENT_MAP:
                return ADT_EVENT_AGENT_MAP[event_type]
        return ENCOUNTER_STATUS_AGENT_MAP.get(
            encounter_status.upper(),
            ("coordinator",),
        )
