---
id: TASK-004
title: "FollowUpCareAgent — A03 Event Consumer, Feature Extraction, Risk Scoring & DB Persistence"
user_story: US-039
epic: EP-007
sprint: 2
layer: Backend / AI Agent
estimate: 5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-039/TASK-001, US-039/TASK-002, US-024, US-017]
---

# TASK-004: FollowUpCareAgent — A03 Event Consumer, Feature Extraction, Risk Scoring & DB Persistence

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039 requires a `FollowUpCareAgent` that:
1. Subscribes to the `adt-events` Pub/Sub topic via `followup-agent-sub`
2. Triggers on A03 (discharge) events only
3. Assembles a 7-feature vector by querying FHIR (comorbidities from `Condition` resources via `FHIRClient.get_conditions()` from US-017) and the SmartHandoff DB (prior admissions count, LOS, age, medication count, discharge disposition, primary diagnosis group)
4. Calls `POST /ml-inference/predict/readmission` on the internal ML Inference Service
5. Persists `encounter.risk_score` and `encounter.risk_tier` to Cloud SQL Primary within 60 seconds of the A03 event (AC Scenario 1)
6. Creates an `AgentTask` record for traceability

The `BaseAgent` subscription loop (Pub/Sub pull, retry, DLQ) is provided by US-024.

**Design references:**
- design.md §3.1 — Follow-up Care Agent: Python LangChain + Scikit-learn, risk scoring
- design.md §3.2 — Agent container pattern (LangChain, Pub/Sub subscription, Pydantic output)
- design.md §9.2 — `followup-agent` Cloud Run: min=1, max=10, 1 vCPU, 1 GB, Concurrency=20
- US-039 AC Scenario 1 — risk_score and risk_tier persisted within 60 s of A03 event
- US-039 AC Scenario 2 — risk tier thresholds: 0.25 → LOW; 0.55 → MEDIUM; 0.72 → HIGH
- US-039 Technical Notes — features: FHIR Condition → num_comorbidities; prior admissions from SmartHandoff DB
- ADR-001 — dedicated Pub/Sub subscription per agent (`followup-agent-sub`) with DLQ
- ADR-004 — LangChain agent framework; Pydantic structured output

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | A03 event → `encounter.risk_score` + `encounter.risk_tier` persisted to DB within 60 s |
| Scenario 2 | Risk tier assignment validated end-to-end (feature extraction → inference → DB) |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/followup_care
touch backend/app/agents/followup_care/__init__.py
touch backend/app/agents/followup_care/agent.py
touch backend/app/agents/followup_care/feature_extractor.py
touch backend/app/agents/followup_care/inference_client.py
touch backend/app/agents/followup_care/schemas.py
touch backend/app/agents/followup_care/main.py
```

### 2. Implement `backend/app/agents/followup_care/schemas.py`

```python
"""Pydantic schemas for FollowUpCareAgent structured output.

Design refs:
    US-039 AC Scenarios 1, 2
    ADR-004 — structured Pydantic output enforced for all agents
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class RiskAssessmentResult(BaseModel):
    """Structured output produced after completing a risk assessment task."""

    encounter_id: str = Field(..., description="UUID of the assessed encounter")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Predicted 30-day readmission probability")
    risk_tier: RiskTier
    model_version: str
    contributing_factors: list[dict] = Field(
        default_factory=list,
        description="Top 5 SHAP contributing factors returned by the ML Inference Service",
    )
    db_updated: bool = False
    agent_task_id: str | None = None
```

### 3. Implement `backend/app/agents/followup_care/feature_extractor.py`

```python
"""Feature extraction for the 30-day readmission risk model.

Retrieves the 7 features required by the ML Inference Service from two sources:
    1. SmartHandoff DB (encounter record, patient record, medication count, prior admissions)
    2. FHIR R4 API (num_comorbidities from Condition resources via US-017 FHIRClient)

FHIR data is used transiently in the agent's working memory — not persisted (AIR-012, C-03).

Feature definitions:
    age                       : Patient age in years at admission (from patient.dob + encounter.admit_date)
    los_days                  : Length of stay = (discharge_date − admit_date).days
    num_comorbidities         : Count of active FHIR Condition resources for the patient
    num_prior_admissions_12mo : Count of DISCHARGED encounters in SmartHandoff DB (past 12 months, excl. current)
    medication_count          : Count of active medications linked to the encounter
    discharge_disposition     : Ordinal-encoded from encounter.discharge_disposition field
    primary_diagnosis_group   : Ordinal-encoded from encounter.admitting_diagnosis using ICD-10 group map
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fhir_client import FHIRClient
from app.models.encounter import Encounter
from app.models.medication import Medication
from app.models.patient import Patient

logger = logging.getLogger(__name__)

# Discharge disposition ordinal encoding — matches config/feature_labels.yaml
DISCHARGE_DISPOSITION_MAP: dict[str, int] = {
    "home": 0,
    "snf": 1,
    "rehab": 2,
    "home_health": 3,
    "ama": 4,
}

# ICD-10 chapter prefix → primary_diagnosis_group index (0–19)
ICD10_GROUP_MAP: dict[str, int] = {
    "I": 0,   # Circulatory
    "J": 1,   # Respiratory
    "M": 2,   # Musculoskeletal
    "G": 3,   # Nervous System
    "K": 4,   # Digestive
    "E": 5,   # Endocrine
    "N": 6,   # Genitourinary
    "A": 7,   # Infectious
    "B": 7,   # Infectious (also)
    "C": 8,   # Neoplasms
    "D": 8,   # Neoplasms (benign)
    "F": 9,   # Mental Health
    "S": 10,  # Injuries
    "T": 10,  # Injuries (also)
    "Z": 11,  # Factors Influencing Health
    "L": 12,  # Skin
    "H": 13,  # Blood
    "Q": 14,  # Hepatobiliary (congenital — approximate)
    "R": 14,  # Hepatobiliary (symptoms — approximate)
    "U": 15,  # Kidney
    "O": 16,  # Female Reproductive
    "P": 17,  # Neonatal
    "V": 18,  # Burns
}
ICD10_GROUP_DEFAULT = 19  # "Other"


async def extract_features(
    session: AsyncSession,
    fhir_client: FHIRClient,
    encounter_id: str,
) -> dict[str, float]:
    """Assemble the 7-feature vector for the readmission risk model.

    Args:
        session: Async SQLAlchemy read session.
        fhir_client: FHIR R4 client (US-017).
        encounter_id: UUID of the discharged encounter.

    Returns:
        Dict mapping feature name → float value, keyed by FEATURE_NAMES order.

    Raises:
        ValueError: If the encounter is not found or is missing required fields.
    """
    # ── Load encounter + patient from DB ─────────────────────────────────────
    result = await session.execute(
        select(Encounter).where(Encounter.id == encounter_id)
    )
    encounter: Encounter | None = result.scalar_one_or_none()
    if encounter is None:
        raise ValueError(f"Encounter not found: {encounter_id}")

    patient_result = await session.execute(
        select(Patient).where(Patient.id == encounter.patient_id)
    )
    patient: Patient | None = patient_result.scalar_one_or_none()
    if patient is None:
        raise ValueError(f"Patient not found for encounter: {encounter_id}")

    # ── age ──────────────────────────────────────────────────────────────────
    admit_date = encounter.admit_date or datetime.datetime.utcnow()
    dob = patient.dob  # datetime.date from encrypted ORM field
    age = (admit_date.date() - dob).days / 365.25

    # ── los_days ─────────────────────────────────────────────────────────────
    discharge_date = encounter.discharge_date or datetime.datetime.utcnow()
    los_days = max(0.0, (discharge_date - encounter.admit_date).total_seconds() / 86400)

    # ── num_comorbidities (FHIR) ──────────────────────────────────────────────
    try:
        conditions = await fhir_client.get_conditions(patient_id=str(encounter.patient_id))
        num_comorbidities = float(len([c for c in conditions if c.clinical_status == "active"]))
    except Exception as exc:
        logger.warning(
            "FHIR Condition fetch failed for encounter_id=%s: %s. Defaulting to 0.",
            encounter_id,
            exc,
        )
        num_comorbidities = 0.0

    # ── num_prior_admissions_12mo (SmartHandoff DB) ──────────────────────────
    cutoff = admit_date - datetime.timedelta(days=365)
    prior_count_result = await session.execute(
        select(func.count(Encounter.id)).where(
            Encounter.patient_id == encounter.patient_id,
            Encounter.status == "DISCHARGED",
            Encounter.discharge_date >= cutoff,
            Encounter.id != encounter.id,
            Encounter.deleted_at.is_(None),
        )
    )
    num_prior_admissions_12mo = float(prior_count_result.scalar_one() or 0)

    # ── medication_count (SmartHandoff DB) ────────────────────────────────────
    med_count_result = await session.execute(
        select(func.count(Medication.id)).where(
            Medication.encounter_id == encounter.id,
            Medication.status == "active",
        )
    )
    medication_count = float(med_count_result.scalar_one() or 0)

    # ── discharge_disposition ─────────────────────────────────────────────────
    disposition_raw = (encounter.discharge_disposition or "home").lower()
    discharge_disposition = float(DISCHARGE_DISPOSITION_MAP.get(disposition_raw, 0))

    # ── primary_diagnosis_group ───────────────────────────────────────────────
    dx = (encounter.admitting_diagnosis or "").upper()
    icd_prefix = dx[0] if dx else ""
    primary_diagnosis_group = float(ICD10_GROUP_MAP.get(icd_prefix, ICD10_GROUP_DEFAULT))

    features = {
        "age": round(age, 2),
        "los_days": round(los_days, 2),
        "num_comorbidities": num_comorbidities,
        "num_prior_admissions_12mo": num_prior_admissions_12mo,
        "medication_count": medication_count,
        "discharge_disposition": discharge_disposition,
        "primary_diagnosis_group": primary_diagnosis_group,
    }

    logger.debug(
        "Features extracted for encounter_id=%s: %s",
        encounter_id,
        # Log only non-PHI values (numeric features)
        {k: v for k, v in features.items()},
    )
    return features
```

### 4. Implement `backend/app/agents/followup_care/inference_client.py`

```python
"""HTTP client for calling the ML Inference Service.

Calls: POST {ML_INFERENCE_SERVICE_URL}/ml-inference/predict/readmission

Design refs:
    US-039 DoD — ML Inference endpoint POST /ml-inference/predict/readmission
    AIR-011     — Async HTTP client (httpx) with exponential backoff retry (3 attempts)
    design.md TR-007 — inference latency < 500ms
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

ML_INFERENCE_URL = os.getenv("ML_INFERENCE_SERVICE_URL", "http://localhost:8081")
_RETRY_ATTEMPTS = 3
_TIMEOUT_SECONDS = 10.0


async def call_readmission_inference(features: dict[str, float]) -> dict:
    """POST to /ml-inference/predict/readmission and return the JSON response.

    Args:
        features: Dict mapping feature names to float values.

    Returns:
        JSON response dict containing ``risk_score``, ``risk_tier``,
        ``contributing_factors``, and ``model_version``.

    Raises:
        RuntimeError: After max retry attempts exhausted.
    """
    url = f"{ML_INFERENCE_URL}/ml-inference/predict/readmission"
    last_exc: Exception | None = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=features)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_exc = exc
            delay = 2 ** (attempt - 1)
            logger.warning(
                "ML inference call failed (attempt %d/%d): %s. Retrying in %ds.",
                attempt, _RETRY_ATTEMPTS, exc, delay,
            )
            if attempt < _RETRY_ATTEMPTS:
                import asyncio
                await asyncio.sleep(delay)

    raise RuntimeError(
        f"ML inference service unavailable after {_RETRY_ATTEMPTS} attempts: {last_exc}"
    )
```

### 5. Implement `backend/app/agents/followup_care/agent.py`

```python
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

import logging
import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent, RetryableError
from app.agents.followup_care.feature_extractor import extract_features
from app.agents.followup_care.inference_client import call_readmission_inference
from app.agents.followup_care.schemas import RiskAssessmentResult, RiskTier
from app.core.fhir_client import FHIRClient
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter

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
    ) -> None:
        super().__init__(subscription_id="followup-agent-sub")
        self._db_session_factory = db_session_factory
        self._read_session_factory = read_session_factory
        self._fhir_client = fhir_client

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
        try:
            async with self._db_session_factory() as write_session:
                await self._update_encounter_risk(
                    session=write_session,
                    encounter_id=encounter_id,
                    risk_score=risk_score,
                    risk_tier=risk_tier_str,
                )
                await self._create_agent_task(
                    session=write_session,
                    agent_task_id=agent_task_id,
                    encounter_id=encounter_id,
                    risk_tier=risk_tier_str,
                    model_version=model_version,
                )
                await write_session.commit()
        except Exception as exc:
            raise RetryableError(f"DB write failed for encounter_id={encounter_id}: {exc}") from exc

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
        )

    async def _update_encounter_risk(
        self,
        session: AsyncSession,
        encounter_id: str,
        risk_score: float,
        risk_tier: str,
    ) -> None:
        """Write risk_score and risk_tier to the encounter record.

        Both fields are defined in the Encounter ORM model (EP-DATA/US-006/TASK-007).
        No Alembic migration required for US-039.
        """
        await session.execute(
            update(Encounter)
            .where(Encounter.id == uuid.UUID(encounter_id))
            .values(risk_score=risk_score, risk_tier=risk_tier)
        )

    async def _create_agent_task(
        self,
        session: AsyncSession,
        agent_task_id: str,
        encounter_id: str,
        risk_tier: str,
        model_version: str,
    ) -> None:
        """Create an AgentTask record for dashboard traceability."""
        task = AgentTask(
            id=uuid.UUID(agent_task_id),
            encounter_id=uuid.UUID(encounter_id),
            agent_type="FOLLOWUP_CARE",
            status=AgentTaskStatus.COMPLETED,
            output_summary=f"Readmission risk assessed: tier={risk_tier} model_version={model_version}",
        )
        session.add(task)
```

### 6. Create Cloud Run entrypoint `backend/app/agents/followup_care/main.py`

```python
"""Cloud Run entrypoint for the Follow-up Care Agent service.

Wires together:
    - FollowUpCareAgent (this task)
    - BaseAgent Pub/Sub pull loop (US-024)
    - FHIRClient (US-017)
    - DB session factories (write → primary; read → replica)
"""
import asyncio
import logging
import os

from app.agents.followup_care.agent import FollowUpCareAgent
from app.core.dependencies import get_read_db, get_write_db
from app.core.fhir_client import FHIRClient

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


async def main() -> None:
    fhir_client = FHIRClient(
        base_url=os.environ["FHIR_BASE_URL"],
        client_id=os.environ["FHIR_CLIENT_ID"],
        client_secret=os.environ["FHIR_CLIENT_SECRET"],
    )
    agent = FollowUpCareAgent(
        db_session_factory=get_write_db,
        read_session_factory=get_read_db,
        fhir_client=fhir_client,
    )
    await agent.run()  # BaseAgent pull loop — blocks until shutdown signal


if __name__ == "__main__":
    asyncio.run(main())
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/followup_care/__init__.py` | Create (empty) |
| `backend/app/agents/followup_care/schemas.py` | Create |
| `backend/app/agents/followup_care/feature_extractor.py` | Create |
| `backend/app/agents/followup_care/inference_client.py` | Create |
| `backend/app/agents/followup_care/agent.py` | Create |
| `backend/app/agents/followup_care/main.py` | Create |

---

## Validation

- [ ] `FollowUpCareAgent.process()` returns `None` for event types other than A03
- [ ] Feature extraction correctly computes `age` from `patient.dob` and `encounter.admit_date`
- [ ] `num_prior_admissions_12mo` query excludes the current encounter (`.id != encounter.id`)
- [ ] FHIR `get_conditions()` failure degrades gracefully — `num_comorbidities` defaults to `0.0` with a WARNING log, not an exception
- [ ] DB update writes both `risk_score` (float) and `risk_tier` (string) in a single transaction
- [ ] `AgentTask` record with `agent_type="FOLLOWUP_CARE"` is created in the same transaction as the encounter update
- [ ] No PHI in any log line — only `encounter_id` (UUID), `risk_score`, `risk_tier`, and `model_version` logged
- [ ] `RetryableError` is raised on DB failures so the Pub/Sub message is nack'd and redelivered (max 5 attempts per TR-015)

---

## Definition of Done

- [ ] `FollowUpCareAgent` implemented extending `BaseAgent`; subscribes to `followup-agent-sub`
- [ ] Feature extraction assembles all 7 required features from FHIR + SmartHandoff DB
- [ ] FHIR `get_conditions()` failure handled gracefully with default=0 and WARNING log
- [ ] `encounter.risk_score` and `encounter.risk_tier` updated in a single atomic DB transaction
- [ ] `AgentTask` record created for traceability on dashboard
- [ ] Cloud Run entrypoint `main.py` wired correctly
- [ ] Code peer-reviewed before merge
