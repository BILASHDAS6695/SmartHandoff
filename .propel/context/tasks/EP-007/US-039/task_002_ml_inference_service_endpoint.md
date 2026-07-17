---
id: TASK-002
title: "ML Inference Service — POST /ml-inference/predict/readmission with SHAP Explanations"
user_story: US-039
epic: EP-007
sprint: 2
layer: Backend / ML Service
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-039/TASK-001, US-001]
---

# TASK-002: ML Inference Service — POST /ml-inference/predict/readmission with SHAP Explanations

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / ML Service | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039 requires an `ml-inference` Cloud Run service that exposes `POST /ml-inference/predict/readmission`. The endpoint:
1. Accepts a structured feature payload (7 features per US-039 Technical Notes)
2. Scales features with `StandardScaler` (pre-loaded from GCS artifact)
3. Runs `LogisticRegression.predict_proba()` to produce a risk probability (0.0–1.0)
4. Computes SHAP values for the top 5 contributing features and maps them to human-readable labels via `config/feature_labels.yaml` (TASK-003)
5. Returns `risk_score`, `risk_tier`, `contributing_factors`, and `model_version`

The model and scaler are loaded once at service startup and held in memory (TR-007: inference latency <500ms, no cold-load per request).

**Design references:**
- design.md §3.1 — ML Inference Service: Python FastAPI + Scikit-learn, Serve readmission risk model
- design.md §4.1 TR-007 — models pre-loaded in container memory; <500ms inference latency
- design.md §9.2 — `ml-inference` Cloud Run: min=1, max=5, 2 vCPU, 2 GB, Concurrency=50
- US-039 AC Scenario 4 — response includes `risk_score`, `risk_tier`, `contributing_factors` (top 5), `model_version`
- US-039 Technical Notes — SHAP `explainer.shap_values()`; map to human-readable labels in `config/feature_labels.yaml`
- ADR-002 — Cloud Run stateless; model artifact loaded from GCS at startup via env var `ML_MODEL_GCS_URI`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Inference endpoint returns `risk_score` and `risk_tier` within 60 s of A03 event (latency < 500 ms per TR-007) |
| Scenario 2 | Risk tier thresholds: probability 0.25 → LOW; 0.55 → MEDIUM; 0.72 → HIGH |
| Scenario 4 | Response includes `risk_score`, `risk_tier`, `contributing_factors` (top 5, human-readable), `model_version` |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p ml-inference/app
touch ml-inference/app/__init__.py
touch ml-inference/app/main.py
touch ml-inference/app/schemas.py
touch ml-inference/app/model_loader.py
touch ml-inference/app/predictor.py
touch ml-inference/app/routers/__init__.py
touch ml-inference/app/routers/predict.py
```

### 2. Implement `ml-inference/app/schemas.py`

```python
"""Request/response Pydantic schemas for the ML Inference Service.

Design refs:
    US-039 AC Scenario 1, 2, 4
    US-039 Technical Notes — 7 features; risk tier thresholds
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReadmissionFeatures(BaseModel):
    """Input feature vector for 30-day readmission risk prediction.

    Feature order must match training.feature_schema.FEATURE_NAMES.
    All values must be present — no imputation in the inference service.
    """

    age: Annotated[float, Field(ge=0, le=120, description="Patient age in years at admission")]
    los_days: Annotated[float, Field(ge=0, description="Length of stay in days")]
    num_comorbidities: Annotated[float, Field(ge=0, description="Active Condition resource count")]
    num_prior_admissions_12mo: Annotated[float, Field(ge=0, description="Prior admissions in last 12 months")]
    medication_count: Annotated[float, Field(ge=0, description="Active medication count at discharge")]
    discharge_disposition: Annotated[
        float,
        Field(ge=0, le=4, description="0=home,1=SNF,2=rehab,3=home_health,4=AMA"),
    ]
    primary_diagnosis_group: Annotated[
        float,
        Field(ge=0, le=19, description="Ordinal-encoded diagnosis group (0–19)"),
    ]


class ContributingFactor(BaseModel):
    """Single SHAP-derived contributing factor with human-readable label."""

    feature: str = Field(..., description="Human-readable feature label from config/feature_labels.yaml")
    shap_value: float = Field(..., description="SHAP value for this feature (positive = increases risk)")
    feature_value: float = Field(..., description="Raw feature value from the input payload")
    direction: str = Field(..., description="'increases_risk' or 'decreases_risk'")


class ReadmissionPredictionResponse(BaseModel):
    """Response from POST /ml-inference/predict/readmission."""

    risk_score: float = Field(..., ge=0.0, le=1.0, description="Predicted 30-day readmission probability")
    risk_tier: RiskTier
    contributing_factors: list[ContributingFactor] = Field(
        ..., max_length=5, description="Top 5 contributing features by absolute SHAP value"
    )
    model_version: str = Field(..., description="Semantic version of the loaded model artifact")


# Risk tier thresholds per US-039 DoD
def assign_risk_tier(probability: float) -> RiskTier:
    """Assign risk tier based on predicted probability.

    Thresholds per US-039:
        LOW    : probability < 0.30
        MEDIUM : 0.30 ≤ probability < 0.70
        HIGH   : probability ≥ 0.70
    """
    if probability >= 0.70:
        return RiskTier.HIGH
    if probability >= 0.30:
        return RiskTier.MEDIUM
    return RiskTier.LOW
```

### 3. Implement `ml-inference/app/model_loader.py`

```python
"""Loads model artifacts from GCS (or local path) at service startup.

The model and scaler are loaded once and held in module-level singletons.
This satisfies TR-007: inference latency <500ms with no cold-load per request.

Environment variables:
    ML_MODEL_GCS_URI  : GCS prefix, e.g. gs://smarthandoff-ml-models/ml-models/readmission-risk/v1
    ML_MODEL_LOCAL_DIR: Local directory for dev/test (overrides GCS)
    ML_MODEL_VERSION  : Semantic version string, e.g. "1.0.0"
"""
from __future__ import annotations

import io
import logging
import os
import pathlib

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

_model: LogisticRegression | None = None
_scaler: StandardScaler | None = None
_model_version: str = "unknown"


def _load_local(directory: str) -> tuple[LogisticRegression, StandardScaler]:
    """Load model and scaler from a local directory (dev/test)."""
    base = pathlib.Path(directory)
    model = joblib.load(base / "model.joblib")
    scaler = joblib.load(base / "scaler.joblib")
    logger.info("Model loaded from local path: %s", directory)
    return model, scaler


def _load_from_gcs(gcs_uri: str) -> tuple[LogisticRegression, StandardScaler]:
    """Download model and scaler bytes from GCS and deserialise in memory."""
    from google.cloud import storage

    # gcs_uri format: gs://bucket/prefix
    assert gcs_uri.startswith("gs://"), f"Invalid GCS URI: {gcs_uri}"
    without_scheme = gcs_uri[5:]
    bucket_name, _, prefix = without_scheme.partition("/")

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    def _download(filename: str):
        blob = bucket.blob(f"{prefix}/{filename}")
        buf = io.BytesIO()
        blob.download_to_file(buf)
        buf.seek(0)
        return joblib.load(buf)

    model = _download("model.joblib")
    scaler = _download("scaler.joblib")
    logger.info("Model loaded from GCS: %s", gcs_uri)
    return model, scaler


def load_model() -> None:
    """Load model + scaler at startup. Called once from FastAPI lifespan."""
    global _model, _scaler, _model_version

    local_dir = os.getenv("ML_MODEL_LOCAL_DIR")
    gcs_uri = os.getenv("ML_MODEL_GCS_URI")
    _model_version = os.getenv("ML_MODEL_VERSION", "unknown")

    if local_dir:
        _model, _scaler = _load_local(local_dir)
    elif gcs_uri:
        _model, _scaler = _load_from_gcs(gcs_uri)
    else:
        raise RuntimeError(
            "Neither ML_MODEL_LOCAL_DIR nor ML_MODEL_GCS_URI is set. "
            "Cannot load readmission risk model."
        )

    logger.info("Readmission risk model v%s loaded successfully.", _model_version)


def get_model() -> LogisticRegression:
    if _model is None:
        raise RuntimeError("Model not loaded. Call load_model() during startup.")
    return _model


def get_scaler() -> StandardScaler:
    if _scaler is None:
        raise RuntimeError("Scaler not loaded. Call load_model() during startup.")
    return _scaler


def get_model_version() -> str:
    return _model_version
```

### 4. Implement `ml-inference/app/predictor.py`

```python
"""Prediction logic: feature scaling, LogisticRegression inference, and SHAP explanations.

Design refs:
    US-039 Technical Notes — SHAP explainer.shap_values(); map to human-readable labels
    US-039 AC Scenario 4   — contributing_factors: top 5 feature importances as human-readable labels
    design.md TR-007       — inference latency < 500ms; model pre-loaded in memory
"""
from __future__ import annotations

import logging

import numpy as np
import shap

from app.model_loader import get_model, get_model_version, get_scaler
from app.schemas import (
    ContributingFactor,
    ReadmissionFeatures,
    ReadmissionPredictionResponse,
    RiskTier,
    assign_risk_tier,
)
from training.feature_schema import FEATURE_NAMES

logger = logging.getLogger(__name__)

# SHAP explainer is initialised lazily on first request and cached
_shap_explainer: shap.LinearExplainer | None = None


def _get_shap_explainer() -> shap.LinearExplainer:
    """Return cached SHAP LinearExplainer (instantiated once)."""
    global _shap_explainer
    if _shap_explainer is None:
        model = get_model()
        scaler = get_scaler()
        # LinearExplainer requires feature mean/variance from training data
        # We use masker=shap.maskers.Independent for logistic regression
        _shap_explainer = shap.LinearExplainer(model, masker=shap.maskers.Independent(
            np.zeros((1, len(FEATURE_NAMES)))
        ))
    return _shap_explainer


def predict(features: ReadmissionFeatures, feature_labels: dict[str, str]) -> ReadmissionPredictionResponse:
    """Run inference and compute SHAP explanations.

    Args:
        features: Validated ``ReadmissionFeatures`` input.
        feature_labels: Mapping of raw feature name → human-readable label
            from ``config/feature_labels.yaml``.

    Returns:
        ``ReadmissionPredictionResponse`` with risk_score, risk_tier,
        contributing_factors (top 5), and model_version.
    """
    model = get_model()
    scaler = get_scaler()
    model_version = get_model_version()

    # Build feature vector in the order expected by the model
    raw_values: dict[str, float] = features.model_dump()
    feature_vector = np.array([raw_values[f] for f in FEATURE_NAMES]).reshape(1, -1)

    # Scale numeric features
    scaled_vector = scaler.transform(feature_vector)

    # Predict probability
    probability = float(model.predict_proba(scaled_vector)[0, 1])
    risk_tier = assign_risk_tier(probability)

    logger.debug("Prediction complete: probability=%.4f tier=%s", probability, risk_tier)

    # SHAP values — top 5 contributing factors
    explainer = _get_shap_explainer()
    shap_values = explainer.shap_values(scaled_vector)[0]  # 1D array of length n_features

    # Sort by absolute SHAP value, descending; take top 5
    sorted_indices = np.argsort(np.abs(shap_values))[::-1][:5]

    contributing_factors: list[ContributingFactor] = []
    for idx in sorted_indices:
        feature_name = FEATURE_NAMES[idx]
        shap_val = float(shap_values[idx])
        contributing_factors.append(
            ContributingFactor(
                feature=feature_labels.get(feature_name, feature_name),
                shap_value=round(shap_val, 4),
                feature_value=float(feature_vector[0, idx]),
                direction="increases_risk" if shap_val > 0 else "decreases_risk",
            )
        )

    return ReadmissionPredictionResponse(
        risk_score=round(probability, 4),
        risk_tier=risk_tier,
        contributing_factors=contributing_factors,
        model_version=model_version,
    )
```

### 5. Implement `ml-inference/app/routers/predict.py`

```python
"""FastAPI router for readmission risk prediction.

Endpoint:
    POST /ml-inference/predict/readmission

Design refs:
    US-039 DoD — ML Inference endpoint POST /ml-inference/predict/readmission
    design.md §3.1 — ML Inference Service serves Scikit-learn models via FastAPI
    SEC: endpoint is internal-only (no public ingress); Cloud Run VPC connector; no JWT required
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.predictor import predict
from app.schemas import ReadmissionFeatures, ReadmissionPredictionResponse

router = APIRouter(prefix="/ml-inference", tags=["inference"])
logger = logging.getLogger(__name__)


def _get_feature_labels(request: Request) -> dict[str, str]:
    """Retrieve feature label mapping loaded at startup from app state."""
    return request.app.state.feature_labels


@router.post(
    "/predict/readmission",
    response_model=ReadmissionPredictionResponse,
    summary="Predict 30-day readmission risk",
    description=(
        "Accepts a 7-feature vector, runs LogisticRegression inference, computes SHAP explanations, "
        "and returns risk_score (0.0–1.0), risk_tier (LOW/MEDIUM/HIGH), top-5 contributing_factors, "
        "and model_version. Internal endpoint — no external JWT required; secured by VPC."
    ),
)
async def predict_readmission(
    features: ReadmissionFeatures,
    feature_labels: dict[str, str] = Depends(_get_feature_labels),
) -> ReadmissionPredictionResponse:
    """Run readmission risk prediction for a discharged encounter."""
    try:
        return predict(features, feature_labels)
    except Exception as exc:
        logger.exception("Prediction failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Readmission risk prediction failed. Check ml-inference service logs.",
        ) from exc
```

### 6. Implement `ml-inference/app/main.py`

```python
"""FastAPI application entrypoint for the ML Inference Service.

Startup sequence:
    1. Load model + scaler from GCS (or local path in dev)
    2. Load feature_labels.yaml from config/
    3. Register /ml-inference/predict/readmission router

Health endpoints:
    GET /health  — liveness probe (TR-016)
    GET /ready   — readiness probe (TR-016); returns 503 if model not loaded
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import yaml
from fastapi import FastAPI

from app.model_loader import load_model
from app.routers.predict import router as predict_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

FEATURE_LABELS_PATH = os.getenv("FEATURE_LABELS_PATH", "config/feature_labels.yaml")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load model artifacts and config at startup; release resources on shutdown."""
    # Load model + scaler (raises RuntimeError if env vars missing)
    load_model()

    # Load feature labels for SHAP human-readable output
    with open(FEATURE_LABELS_PATH, "r") as f:
        app.state.feature_labels = yaml.safe_load(f)
    logger.info("Feature labels loaded from %s", FEATURE_LABELS_PATH)

    yield

    # No cleanup required — GCS client closes automatically


app = FastAPI(
    title="SmartHandoff ML Inference Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,  # Disable Swagger UI in production
    redoc_url=None,
)

app.include_router(predict_router)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "healthy"}


@app.get("/ready", include_in_schema=False)
async def ready() -> dict:
    from app.model_loader import get_model
    try:
        get_model()
        return {"status": "ready"}
    except RuntimeError:
        from fastapi import Response
        return Response(status_code=503, content='{"status":"not_ready","reason":"model_not_loaded"}')
```

### 7. Create `ml-inference/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

---

## File Checklist

| File | Action |
|------|--------|
| `ml-inference/app/__init__.py` | Create (empty) |
| `ml-inference/app/schemas.py` | Create |
| `ml-inference/app/model_loader.py` | Create |
| `ml-inference/app/predictor.py` | Create |
| `ml-inference/app/routers/__init__.py` | Create (empty) |
| `ml-inference/app/routers/predict.py` | Create |
| `ml-inference/app/main.py` | Create |
| `ml-inference/Dockerfile` | Create |

---

## Validation

- [ ] `POST /ml-inference/predict/readmission` with `age=65, los_days=5, num_comorbidities=3, num_prior_admissions_12mo=1, medication_count=6, discharge_disposition=0, primary_diagnosis_group=2` returns HTTP 200 with `risk_score` in [0.0, 1.0] and `risk_tier` in `["LOW","MEDIUM","HIGH"]`
- [ ] `risk_tier=LOW` when `risk_score < 0.30`; `MEDIUM` when `0.30 ≤ risk_score < 0.70`; `HIGH` when `risk_score ≥ 0.70`
- [ ] `contributing_factors` has exactly 5 items; each has `feature`, `shap_value`, `feature_value`, `direction`
- [ ] `model_version` field is non-empty (e.g. `"1.0.0"` or `"unknown"` in dev)
- [ ] `GET /health` returns HTTP 200 `{"status":"healthy"}`
- [ ] `GET /ready` returns HTTP 503 if model not loaded; HTTP 200 if loaded
- [ ] Inference latency p95 < 500ms (validate with `ab -n 100 -c 5` or pytest benchmark)
- [ ] No PHI in any log line — endpoint receives only numeric feature values, not patient identifiers

---

## Definition of Done

- [ ] `POST /ml-inference/predict/readmission` endpoint implemented with SHAP explanations
- [ ] Model + scaler loaded once at startup from GCS/local; no per-request disk I/O
- [ ] Risk tier thresholds correctly applied (LOW < 0.30, MEDIUM 0.30–0.70, HIGH ≥ 0.70)
- [ ] `contributing_factors` returns top 5 SHAP features with human-readable labels
- [ ] `/health` and `/ready` probes implemented for Cloud Run health checks (TR-016)
- [ ] Dockerfile builds and runs locally with `docker build` + `docker run`
- [ ] Code peer-reviewed before merge
