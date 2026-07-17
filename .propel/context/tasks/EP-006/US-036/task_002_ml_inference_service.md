---
id: TASK-002
title: "ML Inference Service — FastAPI Cloud Run Service for Discharge Time Prediction"
user_story: US-036
epic: EP-006
sprint: 2
layer: Backend / ML Serving
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-036/TASK-001]
---

# TASK-002: ML Inference Service — FastAPI Cloud Run Service for Discharge Time Prediction

> **Story:** US-036 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend / ML Serving | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-036 requires a dedicated `ml-inference` Cloud Run service that exposes `POST /ml-inference/predict/discharge-time`. The endpoint accepts an encounter feature vector and returns a predicted discharge time (ISO datetime) plus a confidence interval (±hours), all within 500 ms (TR-007).

The service loads the `GradientBoostingRegressor` pipeline from GCS (`ml-models/discharge_time/latest/discharge_time.joblib`) at startup so the model is pre-warmed in memory — satisfying the <500 ms inference latency requirement without per-request cold loading.

This service is called by the `BedManagementAgent` (TASK-004) whenever an encounter feature changes.

**Design references:**
- design.md §3.1 — ML Inference Service: Python FastAPI + Scikit-learn; serves Cloud Run
- design.md §4.1 — ML serving: FastAPI 0.110+; Scikit-learn 1.5+; model artefact in GCS `ml-models/`
- design.md §5.1 (TR-007) — ML inference latency <500 ms; models pre-loaded in memory
- design.md §9.2 — `ml-inference` Cloud Run: min=1, max=5, 2 vCPU, 2 GB, concurrency=50
- US-036 AC Scenario 1 — POST endpoint returns prediction within 500 ms
- US-036 Technical Notes — confidence thresholds: high if std_dev <1 h; medium 1-2 h; low >2 h
- ADR-002 — Cloud Run stateless service; model pre-loaded at startup

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `POST /ml-inference/predict/discharge-time` returns `predicted_discharge_time` + `confidence_interval` within 500 ms |
| Scenario 3 | Inference service is callable by the BedManagementAgent on any encounter status change |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p ml_inference/app/routers
mkdir -p ml_inference/app/models
touch ml_inference/app/__init__.py
touch ml_inference/app/main.py
touch ml_inference/app/model_loader.py
touch ml_inference/app/schemas.py
touch ml_inference/app/routers/__init__.py
touch ml_inference/app/routers/discharge_time.py
touch ml_inference/Dockerfile
touch ml_inference/requirements.txt
```

### 2. Implement `ml_inference/app/schemas.py`

```python
"""Pydantic request/response schemas for the ML Inference Service.

Design refs:
    US-036 AC Scenario 1 — predicted_discharge_time (ISO datetime) + confidence_interval
    US-036 Technical Notes — confidence thresholds (high <1 h, medium 1-2 h, low >2 h)
    ADR-004 — Pydantic structured output for all AI/ML services
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    HIGH = "high"      # std_dev < 1 hour
    MEDIUM = "medium"  # std_dev 1–2 hours
    LOW = "low"        # std_dev > 2 hours
    UNKNOWN = "unknown"


class DischargeTimePredictionRequest(BaseModel):
    """Feature vector for discharge time inference.

    All features match the training pipeline (train.py). The caller
    (BedManagementAgent) constructs this from the encounter record at inference time.
    """

    encounter_id: str = Field(..., description="Encounter UUID — used for audit and response correlation")
    admit_time: datetime = Field(..., description="UTC-aware admit datetime of the encounter")
    patient_dob: datetime = Field(..., description="Patient date of birth (UTC-aware or date-only)")
    admit_diagnosis_group: str = Field(
        ...,
        description="Broad diagnostic category, e.g. 'CARDIAC', 'ORTHO', 'PULMONARY'",
    )
    unit: str = Field(..., description="Inpatient unit code, e.g. 'ICU', '3A', 'ED'")
    pending_procedures_count: int = Field(
        default=0,
        ge=0,
        description="Number of pending clinical procedures for this encounter",
    )


class DischargeTimePredictionResponse(BaseModel):
    """Discharge time prediction result.

    ``std_dev_hours`` drives the ``confidence_level`` shown in the bed board UI.
    """

    encounter_id: str
    predicted_discharge_time: datetime = Field(
        ...,
        description="Predicted UTC datetime of patient discharge",
    )
    confidence_interval_hours: float = Field(
        ...,
        description="±hours radius of the 80th-percentile prediction interval",
    )
    confidence_level: ConfidenceLevel = Field(
        ...,
        description="Colour-coded confidence tier derived from confidence_interval_hours",
    )
    model_version: str = Field(..., description="Version tag of the model used for this prediction")
```

### 3. Implement `ml_inference/app/model_loader.py`

```python
"""GCS model loader — downloads and caches the discharge time pipeline at startup.

Design refs:
    US-036 DoD — inference service loads latest model on startup
    design.md §5.1 (TR-007) — models pre-loaded in memory; no per-request cold-load
    US-036 Technical Notes — model file: discharge_time/latest/discharge_time.joblib
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import joblib
from google.cloud import storage

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, Any] = {}

GCS_BUCKET = os.environ.get("ML_MODELS_BUCKET", "ml-models")
GCS_OBJECT = "discharge_time/latest/discharge_time.joblib"


def load_model(bucket_name: str = GCS_BUCKET, object_name: str = GCS_OBJECT) -> Any:
    """Download the model from GCS and cache it in memory.

    Uses a module-level cache so subsequent calls within the same Cloud Run
    instance skip the GCS download (critical for sub-500 ms inference latency).

    Args:
        bucket_name: GCS bucket name.
        object_name: GCS object path to the joblib artefact.

    Returns:
        Loaded Scikit-learn ``Pipeline`` object.

    Raises:
        RuntimeError: If the GCS download or joblib deserialization fails.
    """
    cache_key = f"{bucket_name}/{object_name}"
    if cache_key in _MODEL_CACHE:
        logger.debug("Model cache hit: %s", cache_key)
        return _MODEL_CACHE[cache_key]

    logger.info("Loading model from gs://%s/%s", bucket_name, object_name)
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)

        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            blob.download_to_filename(tmp.name)
            pipeline = joblib.load(tmp.name)

        _MODEL_CACHE[cache_key] = pipeline
        logger.info("Model loaded and cached: %s", cache_key)
        return pipeline

    except Exception as exc:
        raise RuntimeError(f"Failed to load model from GCS: gs://{bucket_name}/{object_name}") from exc


def get_model_version(bucket_name: str = GCS_BUCKET) -> str:
    """Return the custom metadata version tag of the latest model blob.

    Falls back to ``"unknown"`` if metadata is unavailable.
    """
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.get_blob("discharge_time/latest/discharge_time.joblib")
        return (blob.metadata or {}).get("version_tag", "unknown") if blob else "unknown"
    except Exception:
        return "unknown"
```

### 4. Implement `ml_inference/app/routers/discharge_time.py`

```python
"""FastAPI router for discharge time prediction endpoint.

Endpoint: POST /ml-inference/predict/discharge-time

Design refs:
    US-036 AC Scenario 1 — returns predicted_discharge_time + confidence_interval within 500 ms
    US-036 Technical Notes — confidence thresholds; los_so_far_hours = (now - admit_time) / 3600
    design.md §5.1 (TR-007) — <500 ms inference latency
    SEC-001 — service account JWT required; validated by FastAPI dependency
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status

from app.model_loader import get_model_version, load_model
from app.schemas import (
    ConfidenceLevel,
    DischargeTimePredictionRequest,
    DischargeTimePredictionResponse,
)
from app.auth import verify_service_account_jwt  # JWT dependency — see Step 5

router = APIRouter(prefix="/ml-inference", tags=["ML Inference"])
logger = logging.getLogger(__name__)

_CONFIDENCE_HIGH_THRESHOLD_H = 1.0
_CONFIDENCE_MEDIUM_THRESHOLD_H = 2.0


def _derive_confidence_level(confidence_interval_hours: float) -> ConfidenceLevel:
    """Map ±hours confidence interval to a colour-coded tier.

    Thresholds per US-036 Technical Notes:
        high   if std_dev < 1 h  → confidence_interval < 1 h
        medium if std_dev 1-2 h  → confidence_interval 1-2 h
        low    if std_dev > 2 h  → confidence_interval > 2 h
    """
    if confidence_interval_hours < _CONFIDENCE_HIGH_THRESHOLD_H:
        return ConfidenceLevel.HIGH
    if confidence_interval_hours < _CONFIDENCE_MEDIUM_THRESHOLD_H:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


@router.post(
    "/predict/discharge-time",
    response_model=DischargeTimePredictionResponse,
    summary="Predict patient discharge time",
    description=(
        "Accepts encounter feature vector and returns the predicted discharge datetime "
        "and ±hour confidence interval. Authenticated via service account JWT."
    ),
    status_code=status.HTTP_200_OK,
)
async def predict_discharge_time(
    request: DischargeTimePredictionRequest,
    _: None = Depends(verify_service_account_jwt),
) -> DischargeTimePredictionResponse:
    """Run inference and return discharge time prediction.

    Args:
        request: Encounter feature vector.

    Returns:
        ``DischargeTimePredictionResponse`` with ISO datetime and confidence tier.

    Raises:
        HTTPException 503: If model is not loaded (startup failure).
        HTTPException 422: FastAPI auto-raises for invalid request body.
    """
    try:
        pipeline = load_model()
    except RuntimeError as exc:
        logger.error("Model unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML model is currently unavailable. Retry after a few seconds.",
        ) from exc

    # Build feature vector — matches train.py feature engineering exactly
    now = datetime.now(timezone.utc)
    admit_time = request.admit_time.replace(tzinfo=timezone.utc) if request.admit_time.tzinfo is None else request.admit_time
    dob = request.patient_dob.replace(tzinfo=timezone.utc) if request.patient_dob.tzinfo is None else request.patient_dob

    los_so_far_hours = max((now - admit_time).total_seconds() / 3600.0, 0.0)
    patient_age = math.floor((admit_time - dob).days / 365.25)

    feature_df = pd.DataFrame([{
        "patient_age": float(patient_age),
        "los_so_far_hours": los_so_far_hours,
        "pending_procedures": float(request.pending_procedures_count),
        "day_of_week": float(admit_time.weekday()),
        "admit_diagnosis_group": request.admit_diagnosis_group,
        "unit": request.unit,
    }])

    # Predict: model returns hours_to_discharge from admit_time
    predicted_hours_from_admit: float = float(pipeline.predict(feature_df)[0])
    predicted_hours_from_admit = max(predicted_hours_from_admit, 0.0)

    predicted_discharge_time = admit_time + timedelta(hours=predicted_hours_from_admit)

    # Derive confidence interval from remaining hours (heuristic: 15% of prediction)
    confidence_interval_hours = round(predicted_hours_from_admit * 0.15, 2)
    confidence_level = _derive_confidence_level(confidence_interval_hours)

    model_version = get_model_version()

    logger.info(
        "Prediction: encounter_id=%s predicted_discharge=%s confidence=%s",
        request.encounter_id,
        predicted_discharge_time.isoformat(),
        confidence_level,
    )

    return DischargeTimePredictionResponse(
        encounter_id=request.encounter_id,
        predicted_discharge_time=predicted_discharge_time,
        confidence_interval_hours=confidence_interval_hours,
        confidence_level=confidence_level,
        model_version=model_version,
    )
```

### 5. Implement `ml_inference/app/auth.py` (service account JWT validation)

```python
"""Service account JWT dependency for ML Inference Service.

Only Cloud Run services with the designated service account may call this endpoint.
The JWT is validated using the Google public key set (OIDC discovery).

Design refs:
    US-036 DoD — POST endpoint auth: service account JWT
    SEC-001 — service-to-service JWT; signed by GCP IAM
"""
from __future__ import annotations

import os

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

_bearer = HTTPBearer()

EXPECTED_AUDIENCE = os.environ.get(
    "ML_INFERENCE_AUDIENCE",
    "https://ml-inference-<hash>-uc.a.run.app",  # overridden at deploy time
)
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

_certs_cache: dict | None = None


async def _get_google_certs() -> dict:
    global _certs_cache
    if _certs_cache is None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(GOOGLE_CERTS_URL, timeout=5.0)
            resp.raise_for_status()
            _certs_cache = resp.json()
    return _certs_cache


async def verify_service_account_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    """Validate a Google-signed service account ID token.

    Raises:
        HTTPException 401: If the token is missing, malformed, or has an invalid signature.
        HTTPException 403: If the token audience does not match the expected audience.
    """
    token = credentials.credentials
    try:
        certs = await _get_google_certs()
        payload = jwt.decode(
            token,
            certs,
            algorithms=["RS256"],
            audience=EXPECTED_AUDIENCE,
            options={"verify_at_hash": False},
        )
        _ = payload  # payload validated; sub is the service account email
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired service account token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
```

### 6. Implement `ml_inference/app/main.py`

```python
"""ML Inference Service — Cloud Run FastAPI entrypoint.

Design refs:
    design.md §9.2 — ml-inference: min=1, max=5, 2 vCPU, 2 GB, concurrency=50
    design.md §5.1 (TR-007) — model pre-loaded at startup (no per-request cold-load)
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.model_loader import load_model
from app.routers.discharge_time import router as discharge_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SmartHandoff ML Inference Service",
    version="1.0.0",
    description="Discharge time prediction endpoint for the Bed Management Agent",
    docs_url=None,   # Disable Swagger UI in production
    redoc_url=None,
)

app.include_router(discharge_router)


@app.on_event("startup")
async def _startup() -> None:
    """Pre-load model into memory at startup to satisfy TR-007 (<500 ms inference)."""
    logger.info("ML Inference Service starting — pre-loading discharge time model...")
    try:
        load_model()
        logger.info("Model pre-loaded successfully.")
    except RuntimeError:
        logger.critical(
            "STARTUP FAILURE: Discharge time model could not be loaded from GCS. "
            "Inference requests will return 503 until the model is available."
        )


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False)
async def ready() -> dict[str, str]:
    """Readiness probe — returns 503 if model not loaded."""
    from app.model_loader import _MODEL_CACHE
    if not _MODEL_CACHE:
        from fastapi import Response
        return Response(status_code=503, content="Model not loaded")
    return {"status": "ready"}
```

### 7. Add `ml_inference/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
```

### 8. Add `ml_inference/requirements.txt`

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
scikit-learn>=1.5.0
pandas>=2.0.0
numpy>=1.26.0
joblib>=1.3.0
google-cloud-storage>=2.14.0
httpx>=0.27.0
python-jose[cryptography]>=3.3.0
pydantic>=2.6.0
```

### 9. Add Terraform Cloud Run resource (reference — implementation in infra-spec)

Cloud Run service config per design.md §9.2:

```hcl
# infra/modules/cloud_run/main.tf (extend existing module)
# ml-inference service
min_instance_count = 1
max_instance_count = 5
cpu                = "2"
memory             = "2Gi"
container_concurrency = 50
env_vars = {
  ML_MODELS_BUCKET     = var.ml_models_bucket_name
  ML_INFERENCE_AUDIENCE = var.ml_inference_audience_url
}
```

---

## Validation Checklist

- [ ] `POST /ml-inference/predict/discharge-time` returns HTTP 200 with valid `DischargeTimePredictionResponse`
- [ ] Response time measured ≤ 500 ms for 10 consecutive requests after warm-up (p95)
- [ ] Model is pre-loaded at startup — `GET /ready` returns 200 before accepting traffic
- [ ] `GET /health` returns HTTP 200
- [ ] Unauthenticated request returns HTTP 401
- [ ] Request with invalid JWT returns HTTP 401 with `WWW-Authenticate: Bearer` header
- [ ] 503 returned with descriptive message if model fails to load from GCS
- [ ] No PHI fields (patient name, MRN, DOB plaintext) appear in application logs
- [ ] Docker image builds successfully: `docker build -t ml-inference:local .`
- [ ] Confidence level correctly maps: prediction < 1 h → `high`; 1-2 h → `medium`; > 2 h → `low`

---

## Definition of Done Checklist (US-036)

| Item | Status |
|------|--------|
| ✅ ML Inference Service Cloud Run: serves GradientBoostingRegressor model via joblib | This task |
| ✅ `POST /ml-inference/predict/discharge-time` FastAPI endpoint (auth: service account JWT) | This task |
| ✅ Inference service loads latest model on startup | This task |
