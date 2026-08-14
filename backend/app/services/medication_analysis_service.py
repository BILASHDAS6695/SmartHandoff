"""AI-powered medication change analysis and readmission prediction.

Produces a structured clinical risk assessment from an encounter's medication
reconciliation data and active pharmacist alerts. The service is designed to be
LLM-ready: it currently uses deterministic clinical heuristics so it works
offline, but the prompt/schema structure can be passed to Gemini Flash for a
more narrative prediction when Vertex AI is configured.

Design refs:
    - SmartHandoff multi-agent architecture — Medication Reconciliation Agent
    - US-030/US-031 — medication reconciliation + interaction alerts
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter, RiskTier
from app.models.medication import Medication, MedicationListSource, ReconciliationCategory
from app.models.pharmacist_alert import PharmacistAlert

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class MedicationAnalysisResult:
    """Structured output for the medication AI analysis endpoint."""

    summary: str
    readmission_risk: str  # "HIGH" | "MEDIUM" | "LOW"
    confidence: str  # "HIGH" | "MEDIUM" | "LOW"
    risks: list[str]
    recommendations: list[str]
    predicted_issues: list[str]
    safety_score: int  # 0-100, higher is safer


class MedicationAnalysisService:
    """Analyses medication reconciliation data and predicts discharge risks."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def analyze(self, encounter_id: UUID) -> MedicationAnalysisResult:
        """Generate a realtime prediction from medication + alert data.

        Args:
            encounter_id: UUID of the encounter to analyse.

        Returns:
            MedicationAnalysisResult with summary, risk, and recommendations.
        """
        encounter = await self._load_encounter(encounter_id)
        medications = await self._load_medications(encounter_id)
        alerts = await self._load_active_alerts(encounter_id)
        history = await self._load_prior_medication_count(encounter)

        return self._analyse(
            encounter=encounter,
            medications=medications,
            alerts=alerts,
            prior_medication_count=history,
        )

    async def _load_encounter(self, encounter_id: UUID) -> Encounter:
        result = await self._db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise ValueError(f"Encounter {encounter_id} not found")
        return encounter

    async def _load_medications(self, encounter_id: UUID) -> list[Medication]:
        result = await self._db.execute(
            select(Medication)
            .where(Medication.encounter_id == encounter_id)
            .order_by(Medication.drug_name)
        )
        return list(result.scalars().all())

    async def _load_active_alerts(self, encounter_id: UUID) -> list[PharmacistAlert]:
        result = await self._db.execute(
            select(PharmacistAlert).where(
                PharmacistAlert.encounter_id == encounter_id,
                PharmacistAlert.status == "ACTIVE",
            )
        )
        return list(result.scalars().all())

    async def _load_prior_medication_count(self, encounter: Encounter) -> int:
        """Count medications from the patient's most recent prior encounter."""
        if not encounter.patient_id:
            return 0

        result = await self._db.execute(
            select(Medication)
            .join(Encounter, Medication.encounter_id == Encounter.id)
            .where(
                Encounter.patient_id == encounter.patient_id,
                Encounter.id != encounter.id,
            )
            .order_by(Encounter.created_at.desc())
            .limit(1)
        )
        # Easiest proxy: count meds in the latest prior encounter via subquery.
        latest = result.scalars().first()
        if latest is None:
            return 0

        count_result = await self._db.execute(
            select(Medication)
            .where(Medication.encounter_id == latest.encounter_id)
        )
        return len(list(count_result.scalars().all()))

    def _analyse(
        self,
        encounter: Encounter,
        medications: list[Medication],
        alerts: list[PharmacistAlert],
        prior_medication_count: int,
    ) -> MedicationAnalysisResult:
        """Run deterministic clinical heuristics to produce a prediction."""
        risks: list[str] = []
        recommendations: list[str] = []
        predicted_issues: list[str] = []

        high_severity_meds = [
            m for m in medications if m.interaction_severity == "HIGH"
        ]
        duplicate_meds = [
            m for m in medications if "DUPLICATE" in (m.flags or [])
        ]
        stopped_meds = [
            m
            for m in medications
            if m.reconciliation_category == ReconciliationCategory.STOPPED
        ]
        new_meds = [
            m
            for m in medications
            if m.reconciliation_category == ReconciliationCategory.NEW
        ]
        dose_changed_meds = [
            m
            for m in medications
            if m.reconciliation_category == ReconciliationCategory.DOSE_CHANGED
        ]
        continued_meds = [
            m
            for m in medications
            if m.reconciliation_category == ReconciliationCategory.CONTINUED
        ]

        # Risk scoring: +3 HIGH, +2 MEDIUM, +1 LOW per factor
        score = 0
        if high_severity_meds:
            score += 3
            names = ", ".join(m.drug_name for m in high_severity_meds)
            risks.append(
                f"Major interaction potential involving {names}. Anticoagulant/antiplatelet "
                "overlap increases bleeding risk and may require INR monitoring."
            )
            recommendations.append(
                "Order baseline and serial INR/PT if not already done; consult pharmacy."
            )
            predicted_issues.append("Bleeding event within 30 days")

        if duplicate_meds:
            score += 2
            names = ", ".join(m.drug_name for m in duplicate_meds)
            risks.append(
                f"Duplicate therapy detected for {names}. Therapeutic duplication can increase "
                "adverse events without added benefit."
            )
            recommendations.append(
                "Review duplicate therapies and discontinue or document intentional overlap."
            )
            predicted_issues.append("Adverse drug event from duplication")

        if stopped_meds:
            score += 2
            names = ", ".join(m.drug_name for m in stopped_meds)
            risks.append(
                f"{names} stopped without explicit discharge order. Chronic condition control "
                "may deteriorate after discharge."
            )
            recommendations.append(
                "Verify intentional discontinuation with prescriber and document reason."
            )
            predicted_issues.append("Disease decompensation from stopped chronic meds")

        if dose_changed_meds:
            score += 1
            names = ", ".join(m.drug_name for m in dose_changed_meds)
            risks.append(
                f"Dose adjustments for {names} increase risk of medication error if old "
                "instructions are used."
            )
            recommendations.append(
                "Highlight dose changes on discharge list and send updated prescriptions to pharmacy."
            )
            predicted_issues.append("Therapeutic error from outdated dosing instructions")

        if new_meds:
            score += 1
            names = ", ".join(m.drug_name for m in new_meds)
            risks.append(
                f"New medications added ({names}). Patient education and adherence monitoring "
                "are needed to prevent early readmission."
            )
            recommendations.append(
                "Provide teach-back education and schedule outpatient med reconciliation within 7 days."
            )
            predicted_issues.append("Medication non-adherence leading to readmission")

        if alerts:
            high_alerts = [a for a in alerts if a.severity == "HIGH"]
            if high_alerts:
                score += 3
                risks.append(
                    f"{len(high_alerts)} unresolved HIGH severity pharmacist alert(s) require review before discharge."
                )
                predicted_issues.append("Unresolved pharmacist alert precipitates adverse event")
            elif alerts:
                score += 1
                risks.append(
                    f"{len(alerts)} active pharmacist alert(s) should be reviewed and resolved."
                )
            recommendations.append("Resolve all active pharmacist alerts and document action taken.")

        # Polypharmacy / regimen complexity factor
        current_count = len(medications)
        if current_count >= 8:
            score += 2
            risks.append(
                f"High medication burden ({current_count} medications). Polypharmacy increases "
                "interaction and adherence risk."
            )
            recommendations.append(
                "Perform dedicated medication therapy management review and simplify regimen where possible."
            )
            predicted_issues.append("Adverse drug event from polypharmacy")
        elif current_count >= 5:
            score += 1

        if prior_medication_count > 0:
            delta = current_count - prior_medication_count
            if delta >= 3:
                score += 1
                risks.append(
                    f"Regimen grew by {delta} medications compared to prior encounter. Rapid "
                    "escalation warrants reconciliation and adherence planning."
                )
                recommendations.append(
                    "Compare new additions against home medication list and confirm each is intentional."
                )
                predicted_issues.append("Regimen complexity shock after discharge")

        # Encounter risk tier amplification
        risk_tier = encounter.risk_tier
        if risk_tier == RiskTier.HIGH:
            score += 2
            risks.append(
                "Encounter risk tier is HIGH. Baseline readmission probability is already elevated."
            )
            recommendations.append(
                "Ensure discharge planning includes follow-up within 48-72 hours for high-risk patients."
            )
        elif risk_tier == RiskTier.MEDIUM:
            score += 1

        # Determine overall readmission risk and safety score
        if score >= 6:
            readmission_risk = "HIGH"
            safety_score = max(0, 40 - score * 3)
            confidence = "HIGH" if alerts or high_severity_meds else "MEDIUM"
        elif score >= 3:
            readmission_risk = "MEDIUM"
            safety_score = max(0, 70 - score * 4)
            confidence = "HIGH" if len(medications) >= 5 else "MEDIUM"
        else:
            readmission_risk = "LOW"
            safety_score = min(100, 95 - score * 5)
            confidence = "HIGH" if current_count > 0 else "MEDIUM"

        if not risks:
            risks.append(
                "No high-priority medication risks identified in the current reconciliation."
            )
            recommendations.append(
                "Continue standard discharge medication counseling."
            )

        # Always include baseline recommendations if none generated
        if not recommendations:
            recommendations.append("Verify medication list accuracy with patient and caregiver.")

        summary = (
            f"Analysis of {current_count} medications shows {len(new_meds)} new, "
            f"{len(stopped_meds)} stopped, {len(dose_changed_meds)} dose-changed, and "
            f"{len(high_severity_meds)} high-severity interaction item(s). "
            f"{len(alerts)} active pharmacist alert(s). "
            f"Predicted 30-day medication-related readmission risk is {readmission_risk} "
            f"(safety score {safety_score}/100)."
        )

        return MedicationAnalysisResult(
            summary=summary,
            readmission_risk=readmission_risk,
            confidence=confidence,
            risks=risks,
            recommendations=recommendations,
            predicted_issues=predicted_issues or ["No specific adverse events predicted"],
            safety_score=safety_score,
        )
