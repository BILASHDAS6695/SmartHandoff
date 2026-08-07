"""FollowUpCareAgent — processes A03 discharge events and persists readmission risk scores.

Subscribes to the ``adt-events`` Pub/Sub topic via ``followup-agent-sub``.
Handles A03 (discharge) events only:
    1. Extracts 7-feature vector (FHIR + SmartHandoff DB)
    2. Calls ML Inference Service → risk_score (0.0–1.0) + risk_tier
    3. Updates encounter.risk_score and encounter.risk_tier in Cloud SQL Primary
    4. Creates AgentTask record for dashboard traceability

Design refs:
    US-039 AC Scenarios 1, 2
    design.md §3.1  — Follow-up Care Agent responsibility
    design.md §3.2  — Agent container pattern
    design.md §9.2  — followup-agent Cloud Run: min=1, max=10, 1 vCPU, 1 GB, concurrency=20
    ADR-001         — dedicated Pub/Sub subscription per agent (followup-agent-sub) with DLQ
    ADR-004         — LangChain agent framework; Pydantic structured output
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent, RetryableError
from app.agents.followup_care.checkin_scheduler import maybe_schedule_48h_checkin
from app.agents.followup_care.feature_extractor import extract_features
from app.agents.followup_care.inference_client import call_readmission_inference
from app.agents.followup_care.schemas import CareManagerAlertPayload, RiskAssessmentResult, RiskTier
from app.config.care_pathways import CarePathwayConfig
from app.core.fhir_client import FHIRClient
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter
from app.services.patient_notification_publisher import PatientNotificationPublisher

logger = logging.getLogger(__name__)


class FollowUpCareAgent(BaseAgent):
    """Processes A03 discharge events to calculate and persist readmission risk scores.

    Inherits Pub/Sub consumption, retry, DLQ handling, and cancellation
    flag checking from ``BaseAgent`` (US-024).

    Args:
        db_session_factory: Async SQLAlchemy session factory (write session — primary DB).
        read_session_factory: Async SQLAlchemy session factory (read session — for feature extraction).
        fhir_client: Initialised ``FHIRClient`` instance (US-017).
    """

    HANDLED_EVENT_TYPES = frozenset({"A03"})

    def __init__(
        self,
        db_session_factory: Any,
        read_session_factory: Any,
        fhir_client: FHIRClient,
        care_pathway_service: Any,
        notification_publisher: Any,
        care_pathway_config: CarePathwayConfig,
    ) -> None:
        super().__init__(subscription_id="followup-agent-sub")
        self._db_session_factory = db_session_factory
        self._read_session_factory = read_session_factory
        self._fhir_client = fhir_client
        self._care_pathway_service = care_pathway_service
        self._notification_publisher = notification_publisher
        self._care_pathway_config = care_pathway_config

    async def process(self, message: dict[str, Any]) -> RiskAssessmentResult | None:
        """Handle a single ADT event message from Pub/Sub.

        Args:
            message: Decoded Pub/Sub message payload containing at minimum
                ``event_type`` and ``encounter_id``.

        Returns:
            ``RiskAssessmentResult`` on success, or ``None`` if event type is not A03.

        Raises:
            RetryableError: On transient failures (DB, FHIR, inference service).
        """
        event_type: str = message["event_type"]
        encounter_id: str = message["encounter_id"]

        if event_type not in self.HANDLED_EVENT_TYPES:
            logger.debug(
                "Skipping event_type=%s encounter_id=%s (not A03)",
                event_type,
                encounter_id,
            )
            return None

        logger.info(
            "Processing A03 risk assessment for encounter_id=%s",
            encounter_id,
        )

        # ── Step 1: Feature extraction ────────────────────────────────────
        try:
            async with self._read_session_factory() as read_session:
                features = await extract_features(
                    session=read_session,
                    fhir_client=self._fhir_client,
                    encounter_id=encounter_id,
                )
        except ValueError as exc:
            # Non-retryable: encounter or patient not found
            logger.error("Feature extraction failed (non-retryable): %s", exc)
            raise
        except Exception as exc:
            raise RetryableError(f"Feature extraction failed: {exc}") from exc

        # ── Step 2: ML Inference Service call ────────────────────────────
        try:
            inference_response = await call_readmission_inference(features)
        except RuntimeError as exc:
            raise RetryableError(f"ML Inference Service unavailable: {exc}") from exc

        risk_score: float = inference_response["risk_score"]
        risk_tier_str: str = inference_response["risk_tier"]
        model_version: str = inference_response.get("model_version", "unknown")
        contributing_factors: list[dict] = inference_response.get("contributing_factors", [])

        # ── Step 3: Persist to DB ─────────────────────────────────────────
        agent_task_id = str(uuid.uuid4())
        appointment_id: str | None = None
        try:
            async with self._db_session_factory() as write_session:
                # Update encounter risk score and tier (US-039)
                encounter = await self._update_encounter_risk(
                    session=write_session,
                    encounter_id=encounter_id,
                    risk_score=risk_score,
                    risk_tier=risk_tier_str,
                )
                
                # Create agent task record (US-039)
                await self._create_agent_task(
                    session=write_session,
                    agent_task_id=agent_task_id,
                    encounter_id=encounter_id,
                    risk_tier=risk_tier_str,
                    model_version=model_version,
                    contributing_factors=contributing_factors,
                )
                
                # ── Step 4: Activate care pathway (US-040) ────────────────────────
                discharge_date = encounter.discharge_date.date() if encounter.discharge_date else None
                if discharge_date:
                    appointment = await self._care_pathway_service.activate_pathway(
                        encounter=encounter,
                        risk_tier=risk_tier_str,
                        discharge_date=discharge_date,
                        db=write_session,
                    )
                    appointment_id = str(appointment.id)
                
                # Commit all changes in single transaction
                await write_session.commit()
        except Exception as exc:
            raise RetryableError(f"DB write failed for encounter_id={encounter_id}: {exc}") from exc
        
        # ── Step 5: Publish CARE_MANAGER_ALERT for HIGH tier (US-040) ─────
        # Publish AFTER commit to avoid sending alerts for rolled-back appointments
        if risk_tier_str == "HIGH" and appointment_id:
            pathway_config = self._care_pathway_config["HIGH"]
            alert_payload = CareManagerAlertPayload(
                encounter_id=encounter_id,
                risk_score=risk_score,
                risk_tier="HIGH",
                required_followup_days=pathway_config.required_followup_days,
                appointment_id=appointment_id,
                idempotency_key=f"CARE_MANAGER_ALERT:{encounter_id}:{appointment_id}",
            )
            try:
                await self._notification_publisher.publish_care_manager_alert(alert_payload)
            except Exception as exc:
                # Log but don't fail the entire process if notification fails
                logger.error(
                    "Failed to publish CARE_MANAGER_ALERT: %s",
                    exc,
                    extra={"encounter_id": encounter_id, "appointment_id": appointment_id},
                )
        
        # ── Step 6: Schedule 48-hour check-in notification (US-041) ───────
        # Schedule AFTER commit for risk_score >= 0.5 (MEDIUM/HIGH risk patients)
        scheduled_notification_id: str | None = None
        checkin_scheduled = False
        try:
            async with self._db_session_factory() as checkin_session:
                # Reload patient to get preferred_contact
                from sqlalchemy import select
                from app.models.patient import Patient
                patient_result = await checkin_session.execute(
                    select(Patient).where(Patient.id == encounter.patient_id)
                )
                patient = patient_result.scalar_one()
                
                # Create ScheduledNotification if risk_score >= 0.5
                scheduled_notification = await maybe_schedule_48h_checkin(
                    session=checkin_session,
                    encounter=encounter,
                    patient=patient,
                    risk_score=risk_score,
                )
                
                if scheduled_notification:
                    await checkin_session.commit()
                    scheduled_notification_id = str(scheduled_notification.id)
                    checkin_scheduled = True
                    logger.info(
                        "check_in_notification_committed",
                        extra={
                            "encounter_id": encounter_id,
                            "scheduled_notification_id": scheduled_notification_id,
                        },
                    )
        except Exception as exc:
            # Log but don't fail the entire risk assessment if check-in scheduling fails
            logger.error(
                "Failed to schedule 48-hour check-in: %s",
                exc,
                extra={"encounter_id": encounter_id},
            )

        # ── Step 7: Patient discharge notification (US-064) ───────────────
        # Inform patient of discharge and follow-up plan. Best-effort; failures logged.
        try:
            async with self._db_session_factory() as notify_session:
                from sqlalchemy import select
                from app.models.patient import Patient
                patient_result = await notify_session.execute(
                    select(Patient).where(Patient.id == encounter.patient_id)
                )
                patient = patient_result.scalar_one_or_none()
                if patient and not patient.notification_opt_out:
                    notifier = PatientNotificationPublisher()
                    follow_up_text = (
                        " A follow-up appointment has been scheduled for you."
                        if appointment_id
                        else ""
                    )
                    await notifier.send_both(
                        phone=patient.phone,
                        email=patient.email,
                        subject="You've been discharged",
                        body=(
                            f"Hi {patient.first_name or 'there'}, you've been discharged. "
                            f"Your care team will follow up via SmartHandoff.{follow_up_text}"
                        ),
                        patient_id=str(patient.id),
                    )
        except Exception as exc:
            logger.error(
                "Failed to send patient discharge notification: %s",
                exc,
                extra={"encounter_id": encounter_id},
            )

        logger.info(
            "Risk assessment complete: encounter_id=%s risk_score=%.4f risk_tier=%s",
            encounter_id,
            risk_score,
            risk_tier_str,
        )

        return RiskAssessmentResult(
            encounter_id=encounter_id,
            risk_score=risk_score,
            risk_tier=RiskTier(risk_tier_str),
            model_version=model_version,
            contributing_factors=contributing_factors,
            db_updated=True,
            agent_task_id=agent_task_id,
            checkin_scheduled=checkin_scheduled,
            scheduled_notification_id=scheduled_notification_id,
        )

    async def _update_encounter_risk(
        self,
        session: AsyncSession,
        encounter_id: str,
        risk_score: float,
        risk_tier: str,
    ) -> Encounter:
        """Write risk_score and risk_tier to the encounter record.

        Both fields are defined in the Encounter ORM model (EP-DATA/US-006/TASK-007).
        No Alembic migration required for US-039.
        
        Returns:
            Updated Encounter ORM object (needed for US-040 care pathway activation).
        """
        await session.execute(
            update(Encounter)
            .where(Encounter.id == uuid.UUID(encounter_id))
            .values(risk_score=risk_score, risk_tier=risk_tier)
        )
        
        # Reload encounter to get updated values and relationships
        from sqlalchemy import select
        result = await session.execute(
            select(Encounter).where(Encounter.id == uuid.UUID(encounter_id))
        )
        encounter = result.scalar_one()
        return encounter

    async def _create_agent_task(
        self,
        session: AsyncSession,
        agent_task_id: str,
        encounter_id: str,
        risk_tier: str,
        model_version: str,
        contributing_factors: list[dict],
    ) -> None:
        """Create an AgentTask record for dashboard traceability.
        
        Stores structured JSON in output_summary for API consumption (TASK-005).
        """
        task = AgentTask(
            id=uuid.UUID(agent_task_id),
            encounter_id=uuid.UUID(encounter_id),
            agent_type="FOLLOWUP_CARE",
            status=AgentTaskStatus.COMPLETED,
            output_summary=json.dumps({
                "risk_tier": risk_tier,
                "model_version": model_version,
                "contributing_factors": contributing_factors,  # list[dict] from inference response
            }),
        )
        session.add(task)
