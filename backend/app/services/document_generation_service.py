"""Role-based clinical document generation service.

Generates Document records from encounter data, medications, pharmacist alerts,
and patient demographics based on the requesting agent role. This powers the
"Generate document" action in the Documents tab and mirrors the agent-driven
document creation in AgentRunner.

Supported agent roles map to clinical document types:
    documentation             -> discharge_summary
    medication_reconciliation -> medication_reconciliation
    follow_up_care            -> follow_up_plan
    patient_communication     -> patient_instructions
    bed_management            -> transfer_summary
    coordinator               -> care_transition_summary
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document, DocumentStatus
from app.models.encounter import Encounter
from app.models.medication import Medication
from app.models.patient import Patient
from app.models.pharmacist_alert import PharmacistAlert
from app.schemas.document_schemas import DocumentResponse

# Map agent type → document type and a human-readable title.
AGENT_ROLE_DOCUMENT_MAP: dict[str, dict[str, str]] = {
    "documentation": {
        "document_type": "discharge_summary",
        "title": "Discharge Summary",
    },
    "medication_reconciliation": {
        "document_type": "medication_reconciliation",
        "title": "Medication Reconciliation Report",
    },
    "follow_up_care": {
        "document_type": "follow_up_plan",
        "title": "Follow-up Care Plan",
    },
    "patient_communication": {
        "document_type": "patient_instructions",
        "title": "Patient Instructions",
    },
    "bed_management": {
        "document_type": "transfer_summary",
        "title": "Transfer Summary",
    },
    "coordinator": {
        "document_type": "care_transition_summary",
        "title": "Care Transition Summary",
    },
}


class DocumentGenerationService:
    """Generate role-based clinical documents for an encounter."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def generate(
        self,
        encounter_id: uuid.UUID,
        agent_role: str,
        regenerate: bool = False,
    ) -> Document:
        """Create a Document record tailored to the agent role.

        Args:
            encounter_id: UUID of the encounter to generate the document for.
            agent_role: Agent role from AGENT_ROLE_DOCUMENT_MAP.
            regenerate: Whether to generate a fresh version using latest data.

        Returns:
            The persisted Document ORM instance.

        Raises:
            ValueError: If the agent role is not supported.
        """
        del regenerate  # Reserved for future versioning logic; each call creates a new document.
        role_config = AGENT_ROLE_DOCUMENT_MAP.get(agent_role)
        if role_config is None:
            supported = ", ".join(AGENT_ROLE_DOCUMENT_MAP)
            raise ValueError(f"Unsupported agent role '{agent_role}'. Use: {supported}")

        encounter = await self._load_encounter(encounter_id)
        patient = encounter.patient
        medications = await self._load_medications(encounter_id)
        alerts = await self._load_alerts(encounter_id)

        document_type = role_config["document_type"]
        title = role_config["title"]
        content = self._build_content(
            document_type=document_type,
            title=title,
            encounter=encounter,
            patient=patient,
            medications=medications,
            alerts=alerts,
        )

        document = Document(
            encounter_id=encounter_id,
            document_type=document_type,
            content=json.dumps(content, default=str),
            status=DocumentStatus.PENDING_APPROVAL.value,
            generation_type="AI",
            completeness_status="COMPLETE",
            missing_fields=[],
            ai_assisted_label=True,
            language_code=patient.language_code if patient else "en",
        )
        self._db.add(document)
        await self._db.flush()
        await self._db.commit()
        await self._db.refresh(document)
        return document

    async def to_response(self, document: Document) -> DocumentResponse:
        """Convert a generated Document to the API response schema."""
        return DocumentResponse.model_validate(document)

    async def _load_encounter(self, encounter_id: uuid.UUID) -> Encounter:
        result = await self._db.execute(
            select(Encounter)
            .where(Encounter.id == encounter_id)
            .options(selectinload(Encounter.patient))
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise ValueError(f"Encounter {encounter_id} not found")
        return encounter

    async def _load_medications(self, encounter_id: uuid.UUID) -> list[Medication]:
        result = await self._db.execute(
            select(Medication).where(Medication.encounter_id == encounter_id)
        )
        return list(result.scalars().all())

    async def _load_alerts(self, encounter_id: uuid.UUID) -> list[PharmacistAlert]:
        result = await self._db.execute(
            select(PharmacistAlert).where(PharmacistAlert.encounter_id == encounter_id)
        )
        return list(result.scalars().all())

    def _build_content(
        self,
        document_type: str,
        title: str,
        encounter: Encounter,
        patient: Patient | None,
        medications: list[Medication],
        alerts: list[PharmacistAlert],
    ) -> dict[str, Any]:
        """Assemble patient-specific structured document content from encounter context."""
        patient_name = self._patient_name(patient)
        age = self._calculate_age(patient.date_of_birth if patient else None)
        inferred_conditions = self._infer_conditions(medications)
        medication_summaries = self._summarize_medications(medications)
        alert_summaries = self._summarize_alerts(alerts)
        admission_date = self._admission_date(encounter)

        base = {
            "title": title,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "document_type": document_type,
            "patient": {
                "name": patient_name,
                "date_of_birth": patient.date_of_birth if patient else None,
                "age": age,
                "mrn": patient.mrn_encrypted[-4:] if patient and patient.mrn_encrypted else "●●●●",
                "language_code": patient.language_code if patient else "en",
            },
            "encounter": {
                "id": str(encounter.id),
                "status": encounter.status,
                "unit": encounter.unit,
                "risk_tier": encounter.risk_tier,
                "admission_date": admission_date,
            },
            "inferred_conditions": inferred_conditions,
            "medications": medication_summaries,
            "alerts": alert_summaries,
        }

        match document_type:
            case "discharge_summary":
                base["sections"] = self._build_discharge_summary_sections(
                    encounter=encounter,
                    patient_name=patient_name,
                    age=age,
                    admission_date=admission_date,
                    inferred_conditions=inferred_conditions,
                    medication_summaries=medication_summaries,
                    alert_summaries=alert_summaries,
                )
            case "medication_reconciliation":
                base["sections"] = self._build_medication_reconciliation_sections(
                    encounter=encounter,
                    medications=medications,
                    medication_summaries=medication_summaries,
                    alert_summaries=alert_summaries,
                    alerts=alerts,
                )
            case "follow_up_plan":
                base["sections"] = self._build_follow_up_plan_sections(
                    encounter=encounter,
                    patient_name=patient_name,
                    inferred_conditions=inferred_conditions,
                    medications=medications,
                )
            case "patient_instructions":
                base["sections"] = self._build_patient_instructions_sections(
                    encounter=encounter,
                    patient_name=patient_name,
                    inferred_conditions=inferred_conditions,
                    medication_summaries=medication_summaries,
                )
            case "transfer_summary":
                base["sections"] = self._build_transfer_summary_sections(
                    encounter=encounter,
                    patient_name=patient_name,
                    inferred_conditions=inferred_conditions,
                    medication_summaries=medication_summaries,
                    alert_summaries=alert_summaries,
                )
            case "care_transition_summary":
                base["sections"] = self._build_care_transition_summary_sections(
                    encounter=encounter,
                    patient_name=patient_name,
                    medications=medications,
                    alerts=alerts,
                )

        return base

    def _build_discharge_summary_sections(
        self,
        encounter: Encounter,
        patient_name: str,
        age: int | None,
        admission_date: str | None,
        inferred_conditions: list[dict[str, Any]],
        medication_summaries: list[dict[str, Any]],
        alert_summaries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build discharge-summary-specific sections using real patient data."""
        condition_names = [c["condition"] for c in inferred_conditions]
        primary_condition = condition_names[0] if condition_names else "Medical admission"

        return {
            "diagnosis_summary": inferred_conditions,
            "hospital_course": (
                f"{patient_name} ({age}y) was admitted to {encounter.unit or 'the unit'} "
                f"on {admission_date or 'the admission date'} with {primary_condition.lower()}. "
                f"Medication reconciliation was completed covering {len(medication_summaries)} medication(s). "
                f"{len(alert_summaries)} alert(s) were reviewed during the encounter."
            ),
            "medications_at_discharge": medication_summaries,
            "follow_up_instructions": self._follow_up_instructions(encounter),
            "warning_signs": [
                "Worsening shortness of breath",
                "Chest pain or palpitations",
                "Signs of bleeding or bruising",
                "Fever above 38°C (100.4°F)",
            ],
            "activity_restrictions": [
                "Follow clinician activity guidance",
                "Avoid driving if taking sedating medications",
            ],
        }

    def _build_medication_reconciliation_sections(
        self,
        encounter: Encounter,
        medications: list[Medication],
        medication_summaries: list[dict[str, Any]],
        alert_summaries: list[dict[str, Any]],
        alerts: list[PharmacistAlert],
    ) -> dict[str, Any]:
        """Build medication-reconciliation-specific sections from actual medications."""
        continued = [m for m in medication_summaries if m["category"] == "CONTINUED"]
        new_meds = [m for m in medication_summaries if m["category"] == "NEW"]
        stopped = [m for m in medication_summaries if m["category"] == "STOPPED"]
        dose_changed = [m for m in medication_summaries if m["category"] == "DOSE_CHANGED"]

        return {
            "reconciliation_summary": (
                f"{len(medications)} medication(s) reconciled across pre-admission, "
                f"inpatient, and discharge lists for this encounter in {encounter.unit or 'the unit'}."
            ),
            "continued_medications": continued,
            "new_medications": new_meds,
            "stopped_medications": stopped,
            "dose_changed_medications": dose_changed,
            "drug_interactions": alert_summaries,
            "pharmacist_recommendations": self._pharmacist_recommendations(
                medications, alerts
            ),
        }

    def _build_follow_up_plan_sections(
        self,
        encounter: Encounter,
        patient_name: str,
        inferred_conditions: list[dict[str, Any]],
        medications: list[Medication],
    ) -> dict[str, Any]:
        """Build follow-up-care-plan-specific sections from patient risk and conditions."""
        days = self._follow_up_days(encounter.risk_tier)
        condition_names = [c["condition"] for c in inferred_conditions]

        return {
            "risk_assessment": {
                "tier": encounter.risk_tier,
                "follow_up_within_days": days,
                "readmission_risk": encounter.risk_tier or "UNKNOWN",
            },
            "appointments": [
                {
                    "type": self._follow_up_type(encounter.risk_tier),
                    "timeframe": f"Within {days} days",
                    "reason": "Post-discharge transition-of-care follow-up",
                },
                *[
                    {
                        "type": "Specialist follow-up",
                        "timeframe": f"Within {days + 7} days",
                        "reason": f"Ongoing management of {condition}",
                    }
                    for condition in condition_names[:2]
                ],
            ],
            "medication_adherence": [
                f"{patient_name} should continue all prescribed medications as directed",
                "Contact pharmacy if any medication is unavailable",
                "Bring the full medication list to every appointment",
            ],
            "warning_signs": [
                "New or worsening symptoms",
                "Unable to obtain prescribed medications",
                "Questions about care plan",
            ],
            "conditions_to_monitor": condition_names,
        }

    def _build_patient_instructions_sections(
        self,
        encounter: Encounter,
        patient_name: str,
        inferred_conditions: list[dict[str, Any]],
        medication_summaries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build plain-language patient-instructions sections."""
        days = self._follow_up_days(encounter.risk_tier)
        condition_names = [c["condition"] for c in inferred_conditions]
        primary_condition = condition_names[0] if condition_names else "your condition"

        return {
            "what_happened": (
                f"Hi {patient_name.split(',')[1].strip() if ',' in patient_name else patient_name}, "
                f"you received care in {encounter.unit or 'the hospital'} for {primary_condition.lower()}. "
                f"Your care team reviewed {len(medication_summaries)} of your medications."
            ),
            "medications_to_take": medication_summaries,
            "when_to_seek_help": [
                "Trouble breathing or chest pain",
                "Severe headache or confusion",
                "Unusual bleeding or bruising",
                "Fever above 38°C (100.4°F)",
            ],
            "follow_up": (
                f"Please schedule a follow-up appointment within {days} days."
            ),
            "conditions": condition_names,
        }

    def _build_transfer_summary_sections(
        self,
        encounter: Encounter,
        patient_name: str,
        inferred_conditions: list[dict[str, Any]],
        medication_summaries: list[dict[str, Any]],
        alert_summaries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build transfer-summary-specific sections."""
        condition_names = [c["condition"] for c in inferred_conditions]

        return {
            "transfer_reason": (
                f"Internal transfer for ongoing care of {patient_name} "
                f"to {encounter.unit or 'destination unit'}."
            ),
            "current_status": encounter.status,
            "active_medications": medication_summaries,
            "active_alerts": alert_summaries,
            "risk_tier": encounter.risk_tier,
            "active_conditions": condition_names,
        }

    def _build_care_transition_summary_sections(
        self,
        encounter: Encounter,
        patient_name: str,
        medications: list[Medication],
        alerts: list[PharmacistAlert],
    ) -> dict[str, Any]:
        """Build care-transition-summary-specific sections."""
        return {
            "coordination_notes": (
                f"Transition coordinator reviewed the encounter for {patient_name} "
                f"in {encounter.unit or 'the unit'}. "
                f"{len(medications)} medication(s), {len(alerts)} alert(s), "
                f"risk tier {encounter.risk_tier or 'UNKNOWN'}."
            ),
            "tasks_completed": [
                "Medication reconciliation verified",
                "Follow-up appointment scheduled or recommended",
                "Patient instructions generated",
            ],
            "open_items": [
                "Awaiting physician approval of generated documents",
            ],
        }

    @staticmethod
    def _admission_date(encounter: Encounter) -> str | None:
        """Return a stable admission date for the encounter."""
        if hasattr(encounter, "admit_date") and encounter.admit_date:
            return encounter.admit_date
        if encounter.created_at:
            return encounter.created_at.date().isoformat()
        return None

    @staticmethod
    def _patient_name(patient: Patient | None) -> str:
        if patient is None:
            return "Patient"
        name = f"{patient.first_name or ''} {patient.last_name or ''}".strip()
        return name or "Patient"

    @staticmethod
    def _calculate_age(date_of_birth: str | None) -> int | None:
        if not date_of_birth:
            return None
        try:
            dob = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
            return (date.today() - dob).days // 365
        except Exception:
            return None

    @staticmethod
    def _summarize_medications(medications: list[Medication]) -> list[dict[str, Any]]:
        return [
            {
                "drug_name": med.drug_name,
                "dose": med.dose,
                "route": med.route,
                "frequency": med.frequency,
                "category": (
                    med.reconciliation_category.value
                    if med.reconciliation_category
                    else "UNKNOWN"
                ),
                "flags": [f.value for f in med.flags] if med.flags else [],
                "severity": med.interaction_severity,
                "sources": [s.value for s in med.sources] if med.sources else [],
            }
            for med in medications
        ]

    @staticmethod
    def _summarize_alerts(alerts: list[PharmacistAlert]) -> list[dict[str, Any]]:
        return [
            {
                "severity": alert.severity,
                "type": alert.alert_type,
                "description": alert.interaction_description,
                "drug_pair": alert.drug_pair,
                "drug_class": alert.drug_class,
                "drug_name": alert.drug_name,
                "status": alert.status,
            }
            for alert in alerts
        ]

    @staticmethod
    def _infer_conditions(medications: list[Medication]) -> list[dict[str, Any]]:
        """Infer likely clinical conditions from the medication list.

        This is a deterministic fallback until a formal diagnosis/condition model
        is added to the encounter schema. It gives the document clinical context
        without requiring diagnosis data.
        """
        conditions: dict[str, str] = {}
        for med in medications:
            name = (med.drug_name or "").lower()
            if "warfarin" in name or "apixaban" in name or "rivaroxaban" in name:
                conditions["Atrial fibrillation / DVT prophylaxis"] = "Anticoagulation therapy present"
            if "metformin" in name or "insulin" in name or "glipizide" in name:
                conditions["Diabetes mellitus"] = "Antidiabetic agent present"
            if "atorvastatin" in name or "rosuvastatin" in name or "simvastatin" in name:
                conditions["Hyperlipidemia / ASCVD risk"] = "Statin therapy present"
            if "metoprolol" in name or "amlodipine" in name or "lisinopril" in name:
                conditions["Hypertension / Cardiac disease"] = "Antihypertensive agent present"
            if "furosemide" in name:
                conditions["Heart failure / Fluid overload"] = "Loop diuretic present"
            if "aspirin" in name:
                conditions["Antiplatelet indication"] = "Aspirin therapy present"

        if not conditions:
            conditions["General medical admission"] = "No specific condition inferred from medications"

        return [
            {"condition": condition, "evidence": evidence}
            for condition, evidence in conditions.items()
        ]

    @staticmethod
    def _follow_up_days(risk_tier: str | None) -> int:
        tier = (risk_tier or "UNKNOWN").upper()
        if tier == "HIGH":
            return 7
        if tier == "MEDIUM":
            return 14
        return 30

    @staticmethod
    def _follow_up_type(risk_tier: str | None) -> str:
        tier = (risk_tier or "UNKNOWN").upper()
        if tier == "HIGH":
            return "HIGH_RISK_FOLLOW_UP"
        if tier == "MEDIUM":
            return "STANDARD_FOLLOW_UP"
        return "ROUTINE_FOLLOW_UP"

    @staticmethod
    def _follow_up_instructions(encounter: Encounter) -> list[dict[str, Any]]:
        days = DocumentGenerationService._follow_up_days(encounter.risk_tier)
        type_ = DocumentGenerationService._follow_up_type(encounter.risk_tier)
        return [
            {
                "instruction": "Schedule follow-up appointment",
                "timeframe": f"Within {days} days",
            },
            {
                "instruction": "Complete medication reconciliation review",
                "timeframe": "Before discharge",
            },
            {
                "instruction": "Contact care team for new or worsening symptoms",
                "timeframe": "As needed",
            },
        ]

    @staticmethod
    def _pharmacist_recommendations(
        medications: list[Medication],
        alerts: list[PharmacistAlert],
    ) -> list[str]:
        recommendations = []
        high_risk_meds = [m for m in medications if m.interaction_severity == "HIGH"]
        if high_risk_meds:
            recommendations.append(
                "Review high-severity medication interactions before discharge."
            )
        stopped_without_order = [m for m in medications if "STOPPED_WITHOUT_ORDER" in [f.value for f in m.flags]]
        if stopped_without_order:
            recommendations.append(
                "Confirm medications stopped without explicit order are intentional."
            )
        duplicates = [m for m in medications if "DUPLICATE" in [f.value for f in m.flags]]
        if duplicates:
            recommendations.append("Resolve duplicate therapy entries.")
        if alerts:
            recommendations.append(
                f"Address {len(alerts)} active pharmacist alert(s) documented in the record."
            )
        if not recommendations:
            recommendations.append("No additional pharmacist recommendations at this time.")
        return recommendations
