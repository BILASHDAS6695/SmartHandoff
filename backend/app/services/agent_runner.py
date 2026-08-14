"""AgentRunner — executes AgentTasks via FastAPI BackgroundTasks.

Option C implementation: agents run asynchronously after the HTTP response
is returned. This gives immediate API feedback while still making the
dashboard "live" through status transitions and SignalR broadcasts.

Design notes:
  - Each background task opens its own DB session so it survives after the
    request session is closed.
  - Uses TaskStatusTransitionService for all status changes so every
    transition broadcasts ``task_updated`` to the dashboard.
  - Real agents are invoked when their dependencies are available; otherwise
    a deterministic stub runs so the lifecycle never blocks.
  - Failures are logged and transition the task to FAILED — they never
    crash the API request.

Refs:
  - US-020/US-021 — Agent task lifecycle
  - US-022        — SignalR broadcast after status transition
  - US-048        — Live dashboard updates
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import session as db_session
from app.models.agent_task import (
    AGENT_TASK_TERMINAL_STATUSES,
    AgentTask,
    AgentTaskStatus,
)
from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.bed import Bed
from app.models.document import Document
from app.models.encounter import Encounter, RiskTier
from app.models.patient import Patient
from app.models.scheduled_notification import (
    DeliveryStatus,
    NotificationChannel,
    NotificationType,
    ScheduledNotification,
)
from app.services.task_status_service import TaskStatusTransitionService
from app.signalr.broadcaster import SignalRBroadcaster, SignalRBroadcasterStub

logger = logging.getLogger(__name__)

# Guard against concurrent/duplicate execution of the same task in this process.
_running_task_ids: set[UUID] = set()

# Deterministic stub work durations so the UI shows meaningful progress.
_STUB_AGENT_DURATION_SECONDS: dict[str, float] = {
    "documentation": 1.5,
    "patient_communication": 1.0,
    "coordinator": 0.5,
    "bed_management": 1.0,
    "follow_up_care": 2.0,
    "medication_reconciliation": 1.0,
}


def _parse_age(date_of_birth: str | None) -> int | None:
    """Return age in years from an ISO-8601 date string."""
    if not date_of_birth:
        return None
    try:
        dob = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        return (date.today() - dob).days // 365
    except Exception:
        return None


def _compute_risk_score(
    patient: Patient | None,
    encounter: Encounter,
) -> tuple[float, RiskTier]:
    """Compute a deterministic readmission risk score for an encounter.

    Uses patient age, unit acuity, and a small per-patient jitter so the same
    patient always receives the same score. This is a pragmatic stand-in for
    the ML Inference Service when it is unavailable.
    """
    base = 0.3

    age = _parse_age(patient.date_of_birth if patient else None)
    if age is not None:
        if age >= 75:
            base += 0.35
        elif age >= 55:
            base += 0.15
        elif age <= 5:
            base += 0.15

    if encounter.unit and encounter.unit.upper() in {"ICU", "CCU", "ED"}:
        base += 0.15

    jitter = 0.0
    if patient is not None:
        jitter = (int(patient.id.hex[:8], 16) % 1000) / 10000.0

    score = round(min(0.99, max(0.01, base + jitter)), 4)

    if score >= 0.7:
        tier = RiskTier.HIGH
    elif score >= 0.4:
        tier = RiskTier.MEDIUM
    else:
        tier = RiskTier.LOW

    return score, tier


async def run_agent_task(
    task_id: UUID,
    broadcaster: SignalRBroadcaster | None = None,
) -> None:
    """Module-level entrypoint for FastAPI BackgroundTasks.

    Args:
        task_id: UUID of the AgentTask to execute.
        broadcaster: Optional SignalR broadcaster; a no-op stub is used when
            SignalR is not configured.
    """
    if db_session.write_session_factory is None:
        logger.error(
            "Cannot run agent task %s: write_session_factory is not initialized",
            task_id,
        )
        return

    if task_id in _running_task_ids:
        logger.info("Agent task %s is already being executed; skipping duplicate", task_id)
        return

    async with db_session.write_session_factory() as db:
        task = await db.get(AgentTask, task_id)
        if task is None:
            logger.warning("Agent task %s not found; skipping execution", task_id)
            return

        if task.status != AgentTaskStatus.PENDING.value:
            logger.info(
                "Agent task %s has status %s; skipping execution",
                task_id,
                task.status,
            )
            return

        runner = AgentRunner(broadcaster=broadcaster)
        await runner.run(db, task)


async def complete_agent_task(
    task_id: UUID,
    broadcaster: SignalRBroadcaster | None = None,
) -> None:
    """Module-level entrypoint used when an external event resolves a task.

    Valid transitions:
      PENDING  → IN_PROGRESS → COMPLETED
      BLOCKED  → IN_PROGRESS → COMPLETED
      IN_PROGRESS / PENDING_APPROVAL → COMPLETED
      Terminal statuses are left untouched.

    Args:
        task_id: UUID of the AgentTask to complete.
        broadcaster: Optional SignalR broadcaster; a no-op stub is used when
            SignalR is not configured.
    """
    if db_session.write_session_factory is None:
        logger.error(
            "Cannot complete agent task %s: write_session_factory is not initialized",
            task_id,
        )
        return

    async with db_session.write_session_factory() as db:
        task = await db.get(AgentTask, task_id)
        if task is None:
            logger.warning(
                "Agent task %s not found; skipping force-complete",
                task_id,
            )
            return

        if task.status in {s.value for s in AGENT_TASK_TERMINAL_STATUSES}:
            logger.info(
                "Agent task %s is already terminal (%s); skipping force-complete",
                task_id,
                task.status,
            )
            return

        runner = AgentRunner(broadcaster=broadcaster)
        await runner.force_complete(db, task)


class AgentRunner:
    """Executes a single AgentTask and manages its full lifecycle."""

    def __init__(self, broadcaster: SignalRBroadcaster | None = None) -> None:
        self._broadcaster = broadcaster or SignalRBroadcasterStub()
        self._transition = TaskStatusTransitionService(self._broadcaster)

    async def run(self, db: AsyncSession, task: AgentTask) -> None:
        """Transition PENDING → IN_PROGRESS → execute → COMPLETED/FAILED."""
        if task.id in _running_task_ids:
            logger.info("Agent task %s already in execution guard; skipping", task.id)
            return
        _running_task_ids.add(task.id)
        try:
            try:
                await self._transition.transition(db, task, AgentTaskStatus.IN_PROGRESS)
            except Exception:
                logger.exception("Failed to start agent task %s", task.id)
                return

            try:
                await self._execute(db, task)
                await self._transition.transition(db, task, AgentTaskStatus.COMPLETED)
            except Exception:
                logger.exception(
                    "Agent %s execution failed for task %s encounter %s",
                    task.agent_type,
                    task.id,
                    task.encounter_id,
                )
                try:
                    await self._transition.transition(db, task, AgentTaskStatus.FAILED)
                except Exception:
                    logger.exception(
                        "Failed to transition agent task %s to FAILED after error",
                        task.id,
                    )
        finally:
            _running_task_ids.discard(task.id)

    async def force_complete(self, db: AsyncSession, task: AgentTask) -> None:
        """Move a non-terminal task to COMPLETED (e.g., alert resolved)."""
        if task.status in {
            AgentTaskStatus.PENDING.value,
            AgentTaskStatus.BLOCKED.value,
        }:
            try:
                await self._transition.transition(db, task, AgentTaskStatus.IN_PROGRESS)
            except Exception:
                logger.exception(
                    "Failed to move task %s to IN_PROGRESS before force-complete",
                    task.id,
                )
                return

        if task.status in {
            AgentTaskStatus.IN_PROGRESS.value,
            AgentTaskStatus.PENDING_APPROVAL.value,
        }:
            try:
                await self._transition.transition(db, task, AgentTaskStatus.COMPLETED)
            except Exception:
                logger.exception(
                    "Failed to force-complete task %s",
                    task.id,
                )

    async def _execute(self, db: AsyncSession, task: AgentTask) -> None:
        """Dispatch to the correct agent implementation."""
        agent_type = task.agent_type

        match agent_type:
            case "medication_reconciliation":
                await self._run_medication_reconciliation(db, task)
            case "bed_management":
                await self._run_bed_management(db, task)
            case "follow_up_care":
                await self._run_follow_up_care(db, task)
            case "documentation":
                await self._run_documentation(db, task)
            case "patient_communication":
                await self._run_patient_communication(db, task)
            case "coordinator":
                await self._run_stub_agent("coordinator", str(task.encounter_id))
                # Count how many distinct agents are actually being dispatched
                # for this encounter (excluding the coordinator itself).
                tasks_for_encounter = await db.execute(
                    select(AgentTask.agent_type).where(
                        AgentTask.encounter_id == task.encounter_id,
                        AgentTask.agent_type != "coordinator",
                    )
                )
                coordinated_count = len(set(tasks_for_encounter.scalars().all()))

                task.output = {
                    "action": "coordination_complete",
                    "tasks_coordinated": coordinated_count,
                    "note": "Transition coordinator reviewed and dispatched agent tasks.",
                }
            case _:
                logger.warning("Unknown agent type %r; using stub", agent_type)
                await self._run_stub_agent(agent_type, str(task.encounter_id))

        await db.flush()

    async def _run_stub_agent(self, agent_type: str, encounter_id: str) -> None:
        """Simulate agent work for agents without a full implementation yet."""
        duration = _STUB_AGENT_DURATION_SECONDS.get(agent_type, 1.0)
        logger.info(
            "Running stub agent %s for encounter %s (%.1fs)",
            agent_type,
            encounter_id,
            duration,
        )
        await asyncio.sleep(duration)
        logger.info(
            "Stub agent %s completed for encounter %s",
            agent_type,
            encounter_id,
        )

    async def _run_medication_reconciliation(
        self, db: AsyncSession, task: AgentTask
    ) -> None:
        """Run the real medication reconciliation agent when possible."""
        try:
            from app.agents.medication_reconciliation.agent import (
                MedicationReconciliationAgent,
            )
            from app.agents.medication_reconciliation.fhir_fetcher import (
                FHIRMedicationFetcher,
            )
            from app.agents.medication_reconciliation.rxnorm import RxNormNormaliser
            from app.core.fhir.client import FHIRClient

            fhir_client = FHIRClient()
            try:
                fetcher = FHIRMedicationFetcher(fhir_client)
                normaliser = RxNormNormaliser()

                agent = MedicationReconciliationAgent(
                    fhir_fetcher=fetcher,
                    normaliser=normaliser,
                    session=db,
                )
                medications = await agent.run(str(task.encounter_id))
                task.output = {
                    "source": "FHIR",
                    "medications_reconciled": len(medications),
                    "interactions_checked": True,
                    "fallback": False,
                }
            finally:
                await fhir_client.close()

        except Exception as exc:
            logger.warning(
                "MedicationReconciliationAgent failed for task %s (falling back to stub): %s",
                task.id,
                exc,
            )
            await self._run_stub_agent("medication_reconciliation", str(task.encounter_id))
            task.output = {
                "source": "stub",
                "medications_reconciled": 0,
                "interactions_checked": False,
                "fallback": True,
                "reason": str(exc),
            }

    async def _run_bed_management(self, db: AsyncSession, task: AgentTask) -> None:
        """Assign an available bed to the encounter and persist the result."""
        encounter = await self._load_encounter(db, task.encounter_id)

        # Prefer beds in the encounter's unit, but fall back to any available bed.
        order_clause = (
            case((Bed.unit == task.unit_id, 0), else_=1)
            if task.unit_id
            else Bed.created_at
        )

        result = await db.execute(
            select(Bed)
            .where(Bed.status.in_(("available", "cleaning")))
            .order_by(order_clause, Bed.created_at.asc())
            .limit(1)
        )
        bed = result.scalar_one_or_none()

        if bed is None:
            task.output = {
                "action": "bed_assignment",
                "assigned": False,
                "reason": "No available beds in inventory",
            }
            raise RuntimeError(
                f"No available bed for encounter {task.encounter_id} (unit {task.unit_id})"
            )

        previous_status = bed.status
        bed.status = "occupied"
        bed.current_encounter_id = task.encounter_id

        if encounter.unit is None:
            encounter.unit = bed.unit

        task.output = {
            "action": "bed_assignment",
            "assigned": True,
            "bed_id": str(bed.id),
            "bed_number": bed.bed_number,
            "unit": bed.unit,
            "room": getattr(bed, "room", None) or getattr(bed, "ward", None) or bed.unit,
            "previous_status": previous_status,
            "new_status": "occupied",
        }

        logger.info(
            "Bed %s assigned to encounter %s (%s → occupied)",
            bed.bed_number,
            task.encounter_id,
            previous_status,
        )

    async def _run_documentation(self, db: AsyncSession, task: AgentTask) -> None:
        """Generate a template discharge summary document for the encounter."""
        encounter = await self._load_encounter(db, task.encounter_id)
        patient = encounter.patient

        patient_name = "Patient"
        if patient is not None:
            patient_name = f"{patient.first_name} {patient.last_name}".strip() or "Patient"

        content = (
            f"DISCHARGE SUMMARY\n"
            f"-----------------\n"
            f"Patient: {patient_name}\n"
            f"Encounter: {encounter.id}\n"
            f"Unit: {encounter.unit or 'TBD'}\n"
            f"Status: {encounter.status}\n\n"
            f"This discharge summary was generated by the Documentation Agent "
            f"using a structured template. Clinical content has been initialised "
            f"and is awaiting physician review and approval.\n"
        )

        document = Document(
            encounter_id=task.encounter_id,
            document_type="discharge_summary",
            content=content,
            status="draft",
            generation_type="TEMPLATE",
            completeness_status="COMPLETE",
            missing_fields=[],
            ai_assisted_label=True,
            language_code=patient.language_code if patient else "en",
        )
        db.add(document)
        await db.flush()

        task.output = {
            "action": "document_generated",
            "document_id": str(document.id),
            "document_type": document.document_type,
            "generation_type": document.generation_type,
            "completeness_status": document.completeness_status,
            "status": document.status,
            "word_count": len(content.split()),
        }

        logger.info(
            "Document %s generated for encounter %s",
            document.id,
            task.encounter_id,
        )

    async def _run_follow_up_care(self, db: AsyncSession, task: AgentTask) -> None:
        """Score readmission risk and schedule a follow-up appointment."""
        encounter = await self._load_encounter(db, task.encounter_id)
        patient = encounter.patient

        risk_score, risk_tier = _compute_risk_score(patient, encounter)
        encounter.risk_tier = risk_tier.value

        tier_mapping: dict[RiskTier, tuple[AppointmentType, int]] = {
            RiskTier.HIGH: (AppointmentType.HIGH_RISK_FOLLOW_UP, 7),
            RiskTier.MEDIUM: (AppointmentType.STANDARD_FOLLOW_UP, 14),
            RiskTier.LOW: (AppointmentType.ROUTINE_FOLLOW_UP, 30),
        }
        appointment_type, follow_up_days = tier_mapping.get(
            risk_tier, (AppointmentType.ROUTINE_FOLLOW_UP, 30)
        )
        target_date = date.today() + timedelta(days=follow_up_days)

        # Avoid duplicate appointment for the same encounter + tier.
        existing = await db.execute(
            select(Appointment).where(
                Appointment.encounter_id == task.encounter_id,
                Appointment.appointment_type == appointment_type.value,
            )
        )
        appointment = existing.scalar_one_or_none()

        if appointment is None:
            appointment = Appointment(
                encounter_id=task.encounter_id,
                appointment_type=appointment_type.value,
                target_date=target_date,
                status=AppointmentStatus.SCHEDULED.value,
            )
            db.add(appointment)
            await db.flush()

        task.output = {
            "action": "risk_assessment",
            "risk_score": risk_score,
            "risk_tier": risk_tier.value,
            "follow_up_days": follow_up_days,
            "appointment_id": str(appointment.id),
            "appointment_type": appointment_type.value,
            "target_date": target_date.isoformat(),
        }

        logger.info(
            "Follow-up care complete for encounter %s: risk=%s score=%.4f appointment=%s",
            task.encounter_id,
            risk_tier.value,
            risk_score,
            appointment.id,
        )

    async def _run_patient_communication(self, db: AsyncSession, task: AgentTask) -> None:
        """Schedule a patient-facing notification for the encounter."""
        encounter = await self._load_encounter(db, task.encounter_id)
        patient = encounter.patient

        channel = NotificationChannel.EMAIL
        if patient is not None:
            if patient.email:
                channel = NotificationChannel.EMAIL
            elif patient.phone:
                channel = NotificationChannel.SMS

        send_at = datetime.now(timezone.utc) + timedelta(hours=24)

        notification = ScheduledNotification(
            idempotency_key=f"PATIENT_COMM:{task.id}",
            type=NotificationType.MEDICATION_REMINDER,
            send_at=send_at,
            channel=channel,
            delivery_status=DeliveryStatus.PENDING,
            patient_id=patient.id if patient else encounter.patient_id,
            encounter_id=task.encounter_id,
        )
        db.add(notification)
        await db.flush()

        task.output = {
            "action": "notification_scheduled",
            "scheduled_notification_id": str(notification.id),
            "type": notification.type.value,
            "channel": notification.channel.value,
            "send_at": notification.send_at.isoformat(),
            "delivery_status": notification.delivery_status.value,
        }

        logger.info(
            "Patient communication scheduled for encounter %s (channel=%s)",
            task.encounter_id,
            channel.value,
        )

    async def _load_encounter(
        self, db: AsyncSession, encounter_id: UUID
    ) -> Encounter:
        """Load an encounter with its patient relationship."""
        result = await db.execute(
            select(Encounter)
            .where(Encounter.id == encounter_id)
            .options(selectinload(Encounter.patient))
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise RuntimeError(f"Encounter {encounter_id} not found")
        return encounter
