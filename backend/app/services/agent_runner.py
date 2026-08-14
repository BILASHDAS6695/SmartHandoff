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
from typing import Any
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.bed_management.scoring import (
    BedRecommendation,
    BedScoringAlgorithm,
    PatientAdmissionProfile,
)
from app.db import session as db_session
from app.models.adt_event import AdtEvent
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
from app.services.medication_generator import (
    generate_alerts_for_reconciliation,
    generate_medications_for_encounter,
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
                # Agents may leave the task in an intermediate state (e.g.
                # PENDING_APPROVAL for bed-management suggestions). Only auto-
                # complete when the status is still IN_PROGRESS.
                if task.status == AgentTaskStatus.IN_PROGRESS.value:
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
        """Run the real medication reconciliation agent when possible.

        If the FHIR-backed agent is unavailable or returns no medications, fall
        back to generating deterministic reconciliation data so the encounter
        always has usable medication records and pharmacist alerts.
        """
        medications: list[Any] = []
        fhir_available = False
        fhir_error: str | None = None

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
                fhir_available = True
            finally:
                await fhir_client.close()

        except Exception as exc:
            fhir_error = str(exc)
            logger.warning(
                "MedicationReconciliationAgent FHIR path failed for task %s: %s",
                task.id,
                exc,
            )

        # Fallback: generate deterministic demo meds when FHIR is unavailable
        # or returned nothing, so the UI and downstream alerts always have data.
        used_fallback = not medications
        if used_fallback:
            encounter = await self._load_encounter(db, task.encounter_id)
            generated = generate_medications_for_encounter(
                task.encounter_id,
                encounter.risk_tier.value if encounter.risk_tier else "UNKNOWN",
            )
            for med in generated:
                db.add(med)
            generate_alerts_for_reconciliation(db, task.encounter_id, generated)
            medications = generated
            logger.info(
                "Generated fallback medications for encounter %s (task %s): %d meds",
                task.encounter_id,
                task.id,
                len(medications),
            )

        task.output = {
            "source": "FHIR" if (fhir_available and not used_fallback) else "fallback_generator",
            "medications_reconciled": len(medications),
            "interactions_checked": fhir_available and not used_fallback,
            "fallback": used_fallback,
            "reason": fhir_error,
        }

    async def _run_bed_management(self, db: AsyncSession, task: AgentTask) -> None:
        """Score vacant beds and publish ranked suggestion(s) for bed manager review.

        The Bed Management Agent no longer auto-assigns beds. Instead it computes
        the best-matching vacant beds using the BedScoringAlgorithm and leaves the
        task in PENDING_APPROVAL so a bed manager can confirm or decline the
        recommendation. This supports the ED boarding alert workflow.
        """
        encounter = await self._load_encounter_with_adt(db, task.encounter_id)
        patient = encounter.patient

        # Build a profile from encounter + latest ADT event. Unknown values are
        # represented with neutral defaults so scoring remains deterministic.
        profile = self._build_patient_admission_profile(encounter)

        # Fetch all currently vacant beds from the primary DB (not the mat view).
        result = await db.execute(
            select(Bed).where(Bed.status.in_(("available", "cleaning", "vacant")))
        )
        vacant_beds = result.scalars().all()

        if not vacant_beds:
            task.output = {
                "action": "bed_suggestion",
                "suggested": False,
                "reason": "No available beds in inventory",
            }
            raise RuntimeError(
                f"No available bed for encounter {task.encounter_id} (unit {task.unit_id})"
            )

        bed_dicts = [
            {
                "bed_id": str(bed.id),
                "unit": bed.unit,
                "room": getattr(bed, "room", None) or getattr(bed, "ward", None) or bed.unit,
                "bed_number": bed.bed_number,
                "bed_type": self._normalize_bed_type(bed.unit),
                "isolation_capable": False,
                "gender_designation": "any",
                "care_type": self._normalize_bed_type(bed.unit),
            }
            for bed in vacant_beds
        ]

        algorithm = BedScoringAlgorithm()
        recommendations: list[BedRecommendation] = algorithm.score_and_rank(
            profile, bed_dicts
        )

        if not recommendations:
            task.output = {
                "action": "bed_suggestion",
                "suggested": False,
                "reason": "No suitable beds matched patient profile",
            }
            raise RuntimeError(
                f"No suitable bed for encounter {task.encounter_id} (unit {task.unit_id})"
            )

        # Compute waiting time for ED boarding context when applicable.
        minutes_waiting = self._estimate_minutes_waiting(encounter)
        acuity_label = profile.acuity_level or "Unknown"

        task.output = {
            "action": "bed_suggestion",
            "suggested": True,
            "encounter_id": str(encounter.id),
            "patient_name": (
                f"{patient.first_name or ''} {patient.last_name or ''}".strip()
                if patient
                else "Unknown"
            ),
            "patient_id": str(patient.id) if patient else None,
            "current_unit": encounter.unit,
            "acuity": acuity_label,
            "minutes_waiting": minutes_waiting,
            "suggestions": [self._bed_recommendation_to_dict(r) for r in recommendations],
            "best_bed_id": recommendations[0].bed_id,
            "best_bed_number": recommendations[0].bed_number,
            "best_bed_unit": recommendations[0].unit,
        }

        # Leave task in PENDING_APPROVAL for bed manager review.
        await self._transition.transition(db, task, AgentTaskStatus.PENDING_APPROVAL)

        logger.info(
            "Bed suggestion generated for encounter %s: best=%s score=%.4f",
            task.encounter_id,
            recommendations[0].bed_number,
            recommendations[0].score,
        )

    def _bed_recommendation_to_dict(self, rec: BedRecommendation) -> dict:
        """Serialize BedRecommendation to a JSON-safe dict."""
        return {
            "bed_id": rec.bed_id,
            "bed_number": rec.bed_number,
            "unit": rec.unit,
            "room": rec.room,
            "score": rec.score,
            "score_breakdown": {
                "acuity_match": rec.score_breakdown.acuity_match,
                "care_type_match": rec.score_breakdown.care_type_match,
                "isolation_match": rec.score_breakdown.isolation_match,
                "gender_match": rec.score_breakdown.gender_match,
            },
        }

    def _normalize_bed_type(self, unit: str | None) -> str:
        """Derive a coarse bed type from unit name for scoring."""
        if not unit:
            return "MED-SURG"
        u = unit.upper()
        if "ICU" in u:
            return "ICU"
        if "STEP" in u or "SDU" in u:
            return "ICU-step-down"
        if "OBS" in u or "ED" in u:
            return "OBS"
        return "MED-SURG"

    def _build_patient_admission_profile(
        self, encounter: Encounter
    ) -> PatientAdmissionProfile:
        """Map encounter + patient to the scoring profile."""
        acuity = "MED-SURG"
        care_type = "GENERAL"
        isolation = False
        gender = "unknown"

        # Derive a sensible default acuity from the encounter unit.
        if encounter.unit:
            unit_upper = encounter.unit.upper()
            if "ICU" in unit_upper:
                acuity = "ICU"
            elif "STEP" in unit_upper or "SDU" in unit_upper:
                acuity = "ICU-step-down"
            elif "OBS" in unit_upper or "ED" in unit_upper:
                acuity = "OBS"

        # Use risk tier as a rough proxy for acuity when unit is generic.
        if acuity == "MED-SURG" and encounter.risk_tier:
            risk = encounter.risk_tier.upper()
            if risk == "HIGH":
                acuity = "ICU-step-down"
            elif risk == "MEDIUM":
                acuity = "MED-SURG"
            else:
                acuity = "OBS"

        return PatientAdmissionProfile(
            acuity_level=acuity,
            admit_type=care_type,
            isolation_required=isolation,
            gender=gender,
        )

    def _latest_adt_event(self, encounter: Encounter) -> AdtEvent | None:
        """Return the most recent ADT event for the encounter, if any."""
        if not encounter.adt_events:
            return None
        return max(
            encounter.adt_events,
            key=lambda e: e.created_at or e.event_timestamp,
            default=None,
        )

    def _estimate_minutes_waiting(self, encounter: Encounter) -> int | None:
        """Estimate how long the patient has been waiting for a bed."""
        from datetime import UTC, datetime

        arrival = encounter.created_at
        if arrival is None:
            return None
        # created_at is timezone-aware; use UTC now for comparison
        delta = datetime.now(UTC) - arrival
        return max(0, int(delta.total_seconds() // 60))

    async def _load_encounter_with_adt(
        self, db: AsyncSession, encounter_id: UUID
    ) -> Encounter:
        """Load an encounter with patient and ADT event relationships."""
        result = await db.execute(
            select(Encounter)
            .where(Encounter.id == encounter_id)
            .options(
                selectinload(Encounter.patient),
                selectinload(Encounter.adt_events),
            )
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise RuntimeError(f"Encounter {encounter_id} not found")
        return encounter

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
