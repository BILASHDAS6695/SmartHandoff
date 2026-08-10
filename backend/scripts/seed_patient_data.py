"""Seed sample medications and documents for local development.

Usage:
    cd backend
    set DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:9432/smarthandoff
    set PHI_ENCRYPTION_KEY=<base64url-encoded-32-byte-key>
    python -m scripts.seed_patient_data

This script inserts:
  - 6 medication reconciliation rows for an existing encounter
  - 1 discharge summary document with structured content

The script is idempotent for the document (upsert by encounter_id + document_type)
but always inserts new medication rows.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Ensure backend package imports work when run as __main__
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.document import Document
from app.models.encounter import Encounter
from app.models.medication import (
    Medication,
    MedicationListSource,
    ReconciliationCategory,
    ReconciliationFlag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [seed_patient_data] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

DEFAULT_ENCOUNTER_ID = uuid.UUID("e9d6a8e1-0234-4a3b-bc39-b07d98008858")

MEDICATIONS = [
    {
        "drug_name": "Warfarin",
        "rxnorm_cui": "11289",
        "dose_value": 5.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "Daily",
        "sources": [MedicationListSource.PRE_ADMIT, MedicationListSource.INPATIENT, MedicationListSource.DISCHARGE],
        "reconciliation_category": ReconciliationCategory.CONTINUED,
        "flags": [],
        "interaction_severity": "HIGH",
    },
    {
        "drug_name": "Aspirin",
        "rxnorm_cui": "1191",
        "dose_value": 81.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "Daily",
        "sources": [MedicationListSource.PRE_ADMIT, MedicationListSource.INPATIENT, MedicationListSource.DISCHARGE],
        "reconciliation_category": ReconciliationCategory.CONTINUED,
        "flags": [ReconciliationFlag.DUPLICATE],
        "interaction_severity": "HIGH",
    },
    {
        "drug_name": "Metformin",
        "rxnorm_cui": "6809",
        "dose_value": 500.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "Twice daily",
        "sources": [MedicationListSource.PRE_ADMIT],
        "reconciliation_category": ReconciliationCategory.STOPPED,
        "flags": [ReconciliationFlag.STOPPED_WITHOUT_ORDER],
        "interaction_severity": "LOW",
    },
    {
        "drug_name": "Metoprolol",
        "rxnorm_cui": "6918",
        "dose_value": 25.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "Twice daily",
        "sources": [MedicationListSource.INPATIENT, MedicationListSource.DISCHARGE],
        "reconciliation_category": ReconciliationCategory.NEW,
        "flags": [],
        "interaction_severity": None,
    },
    {
        "drug_name": "Furosemide",
        "rxnorm_cui": "4603",
        "dose_value": 40.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "Daily",
        "sources": [MedicationListSource.DISCHARGE],
        "reconciliation_category": ReconciliationCategory.NEW,
        "flags": [],
        "interaction_severity": "MEDIUM",
    },
    {
        "drug_name": "Lisinopril",
        "rxnorm_cui": "29046",
        "dose_value": 10.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "Daily",
        "sources": [MedicationListSource.PRE_ADMIT, MedicationListSource.DISCHARGE],
        "reconciliation_category": ReconciliationCategory.DOSE_CHANGED,
        "flags": [],
        "interaction_severity": "LOW",
    },
]

DISCHARGE_CONTENT = {
    "encounter_id": str(DEFAULT_ENCOUNTER_ID),
    "diagnosis_summary": [
        {
            "icd10_code": "I50.23",
            "description": "Acute on chronic systolic heart failure",
            "is_primary": True,
        },
        {
            "icd10_code": "I10",
            "description": "Essential (primary) hypertension",
            "is_primary": False,
        },
    ],
    "hospital_course": (
        "Patient admitted with dyspnea and weight gain. Started on IV diuretics "
        "with 2L net negative fluid balance. Symptoms improved. Weight target <85 kg discussed."
    ),
    "medications_at_discharge": [
        {"drug_name": "Furosemide", "dose": "40 mg", "frequency": "Daily", "route": "oral"},
        {"drug_name": "Lisinopril", "dose": "10 mg", "frequency": "Daily", "route": "oral"},
        {"drug_name": "Metoprolol", "dose": "25 mg", "frequency": "Twice daily", "route": "oral"},
        {"drug_name": "Warfarin", "dose": "5 mg", "frequency": "Daily", "route": "oral"},
        {"drug_name": "Aspirin", "dose": "81 mg", "frequency": "Daily", "route": "oral"},
    ],
    "follow_up_instructions": [
        {"instruction": "Follow up with cardiology in 1 week.", "timeframe": "within 7 days"},
        {"instruction": "Primary care visit within 3-5 days.", "timeframe": "within 3-5 days"},
    ],
    "warning_signs": [
        "Worsening shortness of breath",
        "Rapid weight gain (>2 lb in 1 day)",
        "Swelling in legs or abdomen",
    ],
    "activity_restrictions": [
        "Avoid strenuous activity until cleared by cardiology",
        "Limit salt intake to <2 g per day",
    ],
    "generation_type": "AI",
    "generation_duration_ms": 1240,
}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


async def _find_encounter(session, encounter_id: uuid.UUID) -> Encounter | None:
    return await session.get(Encounter, encounter_id)


async def seed() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        encounter = await _find_encounter(session, DEFAULT_ENCOUNTER_ID)
        if encounter is None:
            logger.error("Encounter %s not found. Aborting.", DEFAULT_ENCOUNTER_ID)
            await engine.dispose()
            return

        logger.info("Seeding data for encounter %s", DEFAULT_ENCOUNTER_ID)

        # ── Medications ───────────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        for med_data in MEDICATIONS:
            medication = Medication(
                encounter_id=DEFAULT_ENCOUNTER_ID,
                drug_name=med_data["drug_name"],
                rxnorm_cui=med_data["rxnorm_cui"],
                dose_value=med_data["dose_value"],
                dose_unit=med_data["dose_unit"],
                route=med_data["route"],
                frequency=med_data["frequency"],
                sources=med_data["sources"],
                reconciliation_category=med_data["reconciliation_category"],
                flags=med_data["flags"],
                interaction_severity=med_data["interaction_severity"],
                reconciliation_completed_at=now,
                source="admission",
                reconciliation_status="reconciled",
            )
            session.add(medication)

        logger.info("Inserted %d medication rows", len(MEDICATIONS))

        # ── Document ──────────────────────────────────────────────────────────
        import json

        existing_doc = await session.execute(
            select(Document).where(
                Document.encounter_id == DEFAULT_ENCOUNTER_ID,
                Document.document_type == "discharge_summary",
            )
        )
        doc = existing_doc.scalar_one_or_none()

        if doc:
            logger.info("Updating existing discharge summary document %s", doc.id)
            doc.content = json.dumps(DISCHARGE_CONTENT)
            doc.status = "pending_approval"
            doc.generation_type = "LLM"
            doc.ai_assisted_label = True
            doc.updated_at = now
        else:
            doc = Document(
                encounter_id=DEFAULT_ENCOUNTER_ID,
                document_type="discharge_summary",
                status="pending_approval",
                generation_type="LLM",
                content=json.dumps(DISCHARGE_CONTENT),
                language_code="en",
                ai_assisted_label=True,
                created_at=now,
                updated_at=now,
            )
            session.add(doc)
            logger.info("Created discharge summary document")

        await session.commit()
        logger.info("Seed complete")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
