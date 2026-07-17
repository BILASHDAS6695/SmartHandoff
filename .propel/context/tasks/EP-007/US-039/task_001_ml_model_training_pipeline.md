---
id: TASK-001
title: "ML Model Training Pipeline — LogisticRegression Readmission Risk Model"
user_story: US-039
epic: EP-007
sprint: 2
layer: ML / Data Science
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-039, EP-DATA/US-006]
---

# TASK-001: ML Model Training Pipeline — LogisticRegression Readmission Risk Model

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** ML / Data Science | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039 requires a Scikit-learn `LogisticRegression` model trained on historical encounter data to predict 30-day hospital readmission risk (probability 0.0–1.0). The model must achieve AUC-ROC ≥ 0.80 on a 20% holdout test set (AC Scenario 3).

This task covers:
- Feature schema definition and synthetic data generation script (for dev/test)
- Training pipeline: preprocessing (`StandardScaler`), model fitting (`LogisticRegression` with L2), holdout evaluation
- Model evaluation report (AUC, precision, recall, F1) exported to GCS
- Model artifact and scaler serialised to GCS `ml-models/readmission-risk/v{N}.joblib`

The `risk_score` and `risk_tier` columns on the `encounter` table are already provisioned by EP-DATA/US-006/TASK-007 — no additional Alembic migration is required.

**Design references:**
- design.md §3.1 — ML Inference Service responsibility (Scikit-learn models served as Cloud Run microservices)
- design.md §4.1 — Scikit-learn 1.5+; LogisticRegression for readmission risk (FR-052, FR-040)
- design.md §5.1 TR-007 — ML inference latency <500ms; models pre-loaded in container memory
- US-039 Technical Notes — LogisticRegression L2; StandardScaler; model stored in GCS `ml-models/readmission-risk/v{N}.joblib`
- US-039 AC Scenario 3 — AUC-ROC ≥ 0.80 on holdout; evaluation report stored in GCS

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 3 | LogisticRegression AUC-ROC ≥ 0.80 evaluated on 20% holdout; report uploaded to GCS |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p ml-inference/training
mkdir -p ml-inference/app
touch ml-inference/training/__init__.py
touch ml-inference/training/train_readmission_risk.py
touch ml-inference/training/generate_synthetic_data.py
touch ml-inference/training/evaluate_model.py
```

### 2. Define feature schema in `ml-inference/training/feature_schema.py`

```python
"""Feature schema for the 30-day readmission risk model.

Features aligned with US-039 Technical Notes and design.md FR-052.
All numeric features are scaled via StandardScaler before model training.
"""
from __future__ import annotations

from dataclasses import dataclass


# Ordered list of feature names — order must match training and inference
FEATURE_NAMES: list[str] = [
    "age",                        # Patient age in years at admission
    "los_days",                   # Length of stay in days
    "num_comorbidities",          # Count of active Condition resources (FHIR)
    "num_prior_admissions_12mo",  # Count of encounters in prior 12 months (SmartHandoff DB)
    "medication_count",           # Number of active medications at discharge
    "discharge_disposition",      # Encoded: 0=home, 1=SNF, 2=rehab, 3=home_health, 4=AMA
    "primary_diagnosis_group",    # Encoded diagnosis group index (0–19); see feature_labels.yaml
]

# Numeric features requiring StandardScaler normalisation
NUMERIC_FEATURES: list[str] = [
    "age",
    "los_days",
    "num_comorbidities",
    "num_prior_admissions_12mo",
    "medication_count",
]

# Categorical features (already ordinally encoded before pipeline)
CATEGORICAL_FEATURES: list[str] = [
    "discharge_disposition",
    "primary_diagnosis_group",
]
```

### 3. Create synthetic data generator `ml-inference/training/generate_synthetic_data.py`

```python
"""Generates a synthetic encounter dataset for local development and CI testing.

NOT used in production — production training uses the SmartHandoff DB + FHIR history.
Generates statistically plausible correlations so AUC ≥ 0.80 is achievable.

Usage:
    python -m training.generate_synthetic_data --output data/synthetic_encounters.csv --n 5000
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from training.feature_schema import FEATURE_NAMES

RANDOM_SEED = 42


def generate(n: int = 5_000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Return a DataFrame of synthetic encounter features with readmission label.

    Label generation logic:
    - Higher prior admissions, more comorbidities, SNF/AMA discharge disposition,
      and longer LOS increase readmission probability.
    - Roughly 20% base readmission rate (realistic for acute care).
    """
    rng = np.random.default_rng(seed)

    age = rng.integers(18, 95, n).astype(float)
    los_days = rng.exponential(4.5, n).clip(1, 90)
    num_comorbidities = rng.poisson(2.8, n).clip(0, 15).astype(float)
    num_prior_admissions_12mo = rng.poisson(0.8, n).clip(0, 10).astype(float)
    medication_count = rng.poisson(5, n).clip(0, 30).astype(float)
    discharge_disposition = rng.choice([0, 1, 2, 3, 4], n, p=[0.55, 0.15, 0.10, 0.15, 0.05])
    primary_diagnosis_group = rng.integers(0, 20, n)

    # Build linear score to generate realistic labels
    logit = (
        -2.5
        + 0.015 * (age - 65)
        + 0.05 * los_days
        + 0.18 * num_comorbidities
        + 0.35 * num_prior_admissions_12mo
        + 0.08 * medication_count
        + np.where(discharge_disposition == 4, 1.2, 0.0)   # AMA discharge
        + np.where(discharge_disposition == 1, 0.5, 0.0)   # SNF
        + rng.normal(0, 0.5, n)                             # noise
    )
    prob = 1 / (1 + np.exp(-logit))
    readmitted_30d = (rng.uniform(size=n) < prob).astype(int)

    return pd.DataFrame(
        {
            "age": age,
            "los_days": los_days,
            "num_comorbidities": num_comorbidities,
            "num_prior_admissions_12mo": num_prior_admissions_12mo,
            "medication_count": medication_count,
            "discharge_disposition": discharge_disposition.astype(float),
            "primary_diagnosis_group": primary_diagnosis_group.astype(float),
            "readmitted_30d": readmitted_30d,
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/synthetic_encounters.csv")
    parser.add_argument("--n", type=int, default=5_000)
    args = parser.parse_args()

    df = generate(args.n)
    df.to_csv(args.output, index=False)
    print(f"Generated {len(df)} rows → {args.output}")
    print(f"Readmission rate: {df['readmitted_30d'].mean():.2%}")
```

### 4. Implement training pipeline `ml-inference/training/train_readmission_risk.py`

```python
"""Training pipeline for 30-day readmission risk LogisticRegression model.

Pipeline:
    1. Load encounter features from CSV (dev) or Cloud SQL (prod via --source=db)
    2. Split 80/20 train/test (stratified)
    3. Scale numeric features with StandardScaler
    4. Fit LogisticRegression (L2, C=1.0, max_iter=500, solver=lbfgs)
    5. Evaluate on holdout: AUC-ROC, precision, recall, F1
    6. Fail the script if AUC < 0.80 (CI quality gate)
    7. Serialise model and scaler to GCS (or local path in dev)

Usage:
    # Development (synthetic data, local output)
    python -m training.train_readmission_risk \
        --source csv --data data/synthetic_encounters.csv \
        --output models/

    # Production (real DB, GCS upload)
    python -m training.train_readmission_risk \
        --source db --db-url postgresql+asyncpg://... \
        --gcs-bucket smarthandoff-ml-models --version 1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    auc,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from training.feature_schema import FEATURE_NAMES, NUMERIC_FEATURES

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Quality gate — CI fails the build if AUC drops below this threshold
MIN_AUC_THRESHOLD = 0.80
RANDOM_SEED = 42


def load_from_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def train(df: pd.DataFrame, output_dir: pathlib.Path) -> dict:
    """Train the readmission risk model and return the evaluation metrics dict.

    Args:
        df: DataFrame with columns matching FEATURE_NAMES + "readmitted_30d".
        output_dir: Local directory to write model artifacts.

    Returns:
        Dict with keys: auc_roc, precision, recall, f1, threshold_low, threshold_high.

    Raises:
        ValueError: If AUC < MIN_AUC_THRESHOLD.
    """
    X = df[FEATURE_NAMES].values
    y = df["readmitted_30d"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=RANDOM_SEED
    )

    # Fit scaler on train only — prevent data leakage
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        max_iter=500,
        random_state=RANDOM_SEED,
        class_weight="balanced",  # Compensate for ~20% readmission base rate
    )
    model.fit(X_train_scaled, y_train)

    # Evaluate on holdout
    y_prob = model.predict_proba(X_test_scaled)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    auc_roc = roc_auc_score(y_test, y_prob)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    logger.info("Holdout evaluation — AUC: %.4f | Precision: %.4f | Recall: %.4f | F1: %.4f",
                auc_roc, precision, recall, f1)

    # Quality gate
    if auc_roc < MIN_AUC_THRESHOLD:
        raise ValueError(
            f"Model AUC {auc_roc:.4f} is below the required threshold {MIN_AUC_THRESHOLD}. "
            "Training failed. Improve feature engineering or increase training data."
        )

    # Serialise model and scaler
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_dir / "model.joblib")
    joblib.dump(scaler, output_dir / "scaler.joblib")
    logger.info("Model artifacts written to %s", output_dir)

    metrics = {
        "auc_roc": round(auc_roc, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "readmission_rate_train": float(y_train.mean()),
        "readmission_rate_test": float(y_test.mean()),
        "min_auc_threshold": MIN_AUC_THRESHOLD,
        "quality_gate": "PASSED",
    }

    # Write evaluation report (JSON)
    report_path = output_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(metrics, indent=2))
    logger.info("Evaluation report written to %s", report_path)

    return metrics


def upload_to_gcs(local_dir: pathlib.Path, bucket: str, version: int) -> None:
    """Upload model artifacts and evaluation report to GCS.

    GCS paths:
        ml-models/readmission-risk/v{N}/model.joblib
        ml-models/readmission-risk/v{N}/scaler.joblib
        ml-models/readmission-risk/v{N}/evaluation_report.json

    Args:
        local_dir: Local directory containing model artifacts.
        bucket: GCS bucket name (e.g. ``"smarthandoff-ml-models"``).
        version: Numeric model version (e.g. ``1``).
    """
    from google.cloud import storage  # Deferred import — not required in dev

    client = storage.Client()
    bucket_obj = client.bucket(bucket)
    prefix = f"ml-models/readmission-risk/v{version}"

    for filename in ["model.joblib", "scaler.joblib", "evaluation_report.json"]:
        local_path = local_dir / filename
        blob = bucket_obj.blob(f"{prefix}/{filename}")
        blob.upload_from_filename(str(local_path))
        logger.info("Uploaded gs://%s/%s/%s", bucket, prefix, filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train readmission risk model")
    parser.add_argument("--source", choices=["csv", "db"], default="csv")
    parser.add_argument("--data", default="data/synthetic_encounters.csv")
    parser.add_argument("--output", default="models/")
    parser.add_argument("--gcs-bucket", default=None)
    parser.add_argument("--version", type=int, default=1)
    args = parser.parse_args()

    if args.source == "csv":
        df = load_from_csv(args.data)
    else:
        raise NotImplementedError("DB source not implemented in this task — use CSV for dev")

    metrics = train(df, pathlib.Path(args.output))

    if args.gcs_bucket:
        upload_to_gcs(pathlib.Path(args.output), args.gcs_bucket, args.version)
        logger.info("Upload complete. Metrics: %s", metrics)
    else:
        logger.info("Local training complete. Metrics: %s", metrics)
```

### 5. Create `ml-inference/requirements.txt`

```
fastapi==0.110.0
uvicorn[standard]==0.29.0
scikit-learn==1.5.0
shap==0.45.0
joblib==1.4.0
numpy==1.26.4
pandas==2.2.1
pydantic==2.7.0
google-cloud-storage==2.16.0
httpx==0.27.0
```

---

## File Checklist

| File | Action |
|------|--------|
| `ml-inference/training/__init__.py` | Create (empty) |
| `ml-inference/training/feature_schema.py` | Create |
| `ml-inference/training/generate_synthetic_data.py` | Create |
| `ml-inference/training/train_readmission_risk.py` | Create |
| `ml-inference/requirements.txt` | Create |

---

## Validation

- [ ] `python -m training.generate_synthetic_data --output data/synthetic_encounters.csv --n 5000` completes; CSV has 8 columns, `readmitted_30d` rate ~20%
- [ ] `python -m training.train_readmission_risk --source csv --data data/synthetic_encounters.csv --output models/` completes; `models/evaluation_report.json` exists; `auc_roc ≥ 0.80`
- [ ] Script exits non-zero (raises `ValueError`) if AUC < 0.80
- [ ] `models/model.joblib` and `models/scaler.joblib` are valid joblib files loadable with `joblib.load()`
- [ ] No patient PHI in any training script output or log line
- [ ] `upload_to_gcs()` correctly maps local files to `ml-models/readmission-risk/v{N}/` GCS prefix

---

## Definition of Done

- [ ] Feature schema (`FEATURE_NAMES`, `NUMERIC_FEATURES`) defined and documented
- [ ] Synthetic data generator produces realistic class imbalance (~20% readmission rate)
- [ ] Training pipeline produces `model.joblib`, `scaler.joblib`, `evaluation_report.json`
- [ ] AUC-ROC ≥ 0.80 quality gate enforced and CI will fail if not met
- [ ] GCS upload path follows `ml-models/readmission-risk/v{N}/` convention
- [ ] Code peer-reviewed before merge
