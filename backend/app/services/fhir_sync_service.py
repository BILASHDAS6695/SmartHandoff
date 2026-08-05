"""FHIR Patient Sync Service — Load FHIR data into database with duplicate prevention.

Fetches FHIR patients from SMART Health IT server and syncs to PostgreSQL database
with duplicate checking via mrn_encrypted only (fhir_id added after migration).

Design refs:
    US-XXX AC1 — FHIR data sync with duplicate prevention
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import get_settings
from app.core.fhir.models import PatientModel
from app.models.patient import Patient
from app.models.encounter import Encounter, EncounterStatus, RiskTier
from app.services.fhir_patient_service import FHIRPatientService

logger = logging.getLogger(__name__)


class FHIRSyncResult:
    """Result of FHIR sync operation."""

    def __init__(self) -> None:
        self.inserted: int = 0
        self.skipped_duplicate_mrn: int = 0
        self.errors: list[str] = []
        self.total_attempted: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "inserted": self.inserted,
            "skipped_duplicate_mrn": self.skipped_duplicate_mrn,
            "errors": self.errors,
            "total_attempted": self.total_attempted,
            "status": "success" if not self.errors else "partial_success",
        }


class FHIRSyncService:
    """Service to sync FHIR patients to database with duplicate prevention."""

    def __init__(self, db_session: AsyncSession) -> None:
        """Initialize with database session."""
        self.db_session = db_session
        self.fhir_service = FHIRPatientService()
        self.settings = get_settings()

    async def sync_fhir_patients(self, limit: int = 100) -> FHIRSyncResult:
        """Sync FHIR patients to database with duplicate prevention.

        Args:
            limit: Maximum number of FHIR patients to sync per request

        Returns:
            FHIRSyncResult with insert/skip statistics
        """
        result = FHIRSyncResult()

        try:
            logger.info(f"[SYNC] Starting FHIR fetch (limit={limit})")
            
            # Step 1: Fetch FHIR patients
            fhir_patients = await self.fhir_service.get_all_patients(limit=limit)
            result.total_attempted = len(fhir_patients)
            
            logger.info(f"[SYNC] Fetched {len(fhir_patients)} patients from FHIR")

            if not fhir_patients:
                logger.warning("[SYNC] No FHIR patients returned from FHIR server")
                return result

            logger.info(f"[SYNC] Starting database insert for {len(fhir_patients)} patients")
            
            # Step 2: Insert into database
            for idx, fhir_patient in enumerate(fhir_patients):
                try:
                    logger.debug(f"[SYNC] Processing patient {idx+1}/{len(fhir_patients)}: {fhir_patient.given_name} {fhir_patient.family_name}")
                    await self._sync_single_patient(fhir_patient, result)
                except Exception as e:
                    error_msg = f"Error syncing patient {fhir_patient.id}: {str(e)}"
                    logger.error(f"[SYNC] {error_msg}", exc_info=True)
                    result.errors.append(error_msg)

            # Commit all changes
            logger.info(f"[SYNC] Committing {result.inserted} inserts + encounters to database")
            try:
                await self.db_session.commit()
                logger.info(f"[SYNC] ✓ COMMIT SUCCESSFUL: {result.inserted} patients + encounters committed")
            except Exception as commit_err:
                logger.error(f"[SYNC] ✗ COMMIT FAILED: {commit_err}", exc_info=True)
                result.errors.append(f"Database commit failed: {str(commit_err)}")
                raise
            
            logger.info(
                f"[SYNC] COMPLETE: {result.inserted} inserted, "
                f"{result.skipped_duplicate_mrn} skipped (mrn)"
            )

        except Exception as e:
            error_msg = f"FHIR sync failed: {str(e)}"
            logger.error(f"[SYNC] {error_msg}", exc_info=True)
            result.errors.append(error_msg)
            try:
                await self.db_session.rollback()
                logger.info("[SYNC] Rolled back transaction")
            except Exception as rollback_err:
                logger.error(f"[SYNC] Rollback failed: {rollback_err}")

        return result

    async def _sync_single_patient(
        self, fhir_patient: PatientModel, result: FHIRSyncResult
    ) -> None:
        """Sync a single FHIR patient with duplicate checking.

        Args:
            fhir_patient: PatientModel from FHIR
            result: FHIRSyncResult to track stats

        Raises:
            Exception: On database or validation error
        """
        logger.debug(f"[SYNC-PATIENT] Starting patient sync: {fhir_patient.id}")
        
        # Check if already exists by MRN (using SQLAlchemy ORM encryption)
        if fhir_patient.mrn:
            logger.debug(f"[SYNC-PATIENT] Checking for duplicate MRN: {fhir_patient.mrn}")
            try:
                # Query by MRN - ORM handles decryption/encryption
                existing = await self.db_session.execute(
                    select(Patient).where(Patient.mrn_encrypted == fhir_patient.mrn)
                )
                if existing.scalar_one_or_none():
                    result.skipped_duplicate_mrn += 1
                    logger.debug(f"[SYNC-PATIENT] Patient with MRN {fhir_patient.mrn} already exists, skipping")
                    return
                logger.debug(f"[SYNC-PATIENT] MRN check passed, patient is new")
            except Exception as e:
                logger.error(f"[SYNC-PATIENT] MRN check failed: {e}", exc_info=True)
                raise

        # Create new patient with auto-generated UUID
        logger.debug(f"[SYNC-PATIENT] Creating new patient record")
        try:
            new_patient = Patient(
                id=uuid.uuid4(),  # Generate UUID
                fhir_id=fhir_patient.id if hasattr(Patient, 'fhir_id') else None,
                first_name=fhir_patient.given_name or "Unknown",
                last_name=fhir_patient.family_name or "Unknown",
                date_of_birth=(
                    fhir_patient.birth_date.isoformat()
                    if fhir_patient.birth_date
                    else "1900-01-01"
                ),
                mrn_encrypted=fhir_patient.mrn or f"FHIR-{fhir_patient.id}",
                phone=fhir_patient.phone,
                email=fhir_patient.email,
                language_code="en",
                resolution_method="MRN",
                partial_match=fhir_patient.partial_match,
                notification_opt_out=False,
            )
            
            # Log the values being set
            logger.debug(
                f"[SYNC-PATIENT] Patient object created with values:\n"
                f"  first_name={new_patient.first_name!r}\n"
                f"  last_name={new_patient.last_name!r}\n"
                f"  date_of_birth={new_patient.date_of_birth!r}\n"
                f"  mrn_encrypted={new_patient.mrn_encrypted!r}"
            )
            
            logger.debug(f"[SYNC-PATIENT] Adding patient to session: {fhir_patient.given_name} {fhir_patient.family_name}")
            self.db_session.add(new_patient)
            result.inserted += 1
            logger.debug(f"[SYNC-PATIENT] Patient added successfully")
            
            # Flush to ensure patient is inserted before encounter
            try:
                await self.db_session.flush()
                logger.debug(f"[SYNC-PATIENT] Patient flushed to database with ID: {new_patient.id}")
            except Exception as flush_err:
                logger.error(f"[SYNC-PATIENT] Failed to flush patient: {flush_err}", exc_info=True)
                raise
            
            # Create a synthetic encounter for this patient so it appears in GET /patients endpoint
            logger.debug(f"[SYNC-PATIENT] Creating synthetic encounter for patient {new_patient.id}")
            try:
                new_encounter = Encounter(
                    id=uuid.uuid4(),
                    patient_id=new_patient.id,
                    status=EncounterStatus.ADMITTED.value,
                    patient_resolution_status="RESOLVED",
                    unit="ICU",
                    risk_tier=RiskTier.UNKNOWN.value,
                )
                self.db_session.add(new_encounter)
                logger.debug(f"[SYNC-PATIENT] Encounter created and added successfully")
                
                # Flush encounter to database immediately
                try:
                    await self.db_session.flush()
                    logger.debug(f"[SYNC-PATIENT] Encounter flushed successfully: {new_encounter.id}")
                except Exception as enc_flush_err:
                    logger.error(f"[SYNC-PATIENT] Failed to flush encounter: {enc_flush_err}", exc_info=True)
                    raise
                    
            except Exception as encounter_err:
                logger.error(f"[SYNC-PATIENT] Failed to create/flush encounter: {encounter_err}", exc_info=True)
                # Still continue sync but log that encounter is missing
                logger.warning(f"[SYNC-PATIENT] WARNING: Encounter not created for patient {new_patient.id} - this patient will not appear in GET /patients endpoint")
            
        except Exception as e:
            logger.error(f"[SYNC-PATIENT] Failed to create patient record: {e}", exc_info=True)
            raise

