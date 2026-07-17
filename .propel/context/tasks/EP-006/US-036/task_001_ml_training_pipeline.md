---
id: TASK-001
title: "Discharge Time ML Model — Feature Engineering, Training, and Evaluation Pipeline"
user_story: US-036
epic: EP-006
sprint: 2
layer: ML / Data Science
estimate: 5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-035/TASK-001]
---

# TASK-001: Discharge Time ML Model — Feature Engineering, Training, and Evaluation Pipeline

> **Story:** US-036 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** ML / Data Science | **Est:** 5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-036 requires a `GradientBoostingRegressor` model that predicts patient discharge time within ±2 hours for 80% of encounters (MAE ≤ 2 hours). This task implements the full training pipeline: feature extraction from the Cloud SQL `encounter` table, model training with hyperparameter defaults, evaluation on a 20% holdout set, and serialisation of the trained model artefact to GCS (`ml-models/discharge_time_v1.joblib`).

The trained artefact is the prerequisite for TASK-002 (ML Inference Service). All evaluation thresholds map directly to US-036 Acceptance Criteria Scenario 2.

**Design references:**
- design.md §3.1 — ML Inference Service responsibility (Scikit-learn, GradientBoosting)
- design.md §4.1 — Scikit-learn 1.5+; `FastAPI` ML serving service; GCS `ml-models/` bucket
- design.md §5.1 (TR-007) — ML inference latency <500 ms (model must be pre-loadable from `joblib`)
- US-036 Technical Notes — feature list, `los_so_far_hours` derivation, model refresh nightly
- US-036 DoD — MAE ≤ 2 h; 80% within ±2 h; GCS version tag; `models/discharge_time_v1.joblib`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | Model evaluated on 20% holdout: ≥80% predictions within ±2 h; MAE ≤2 h |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p ml/discharge_time_model
touch ml/discharge_time_model/__init__.py
touch ml/discharge_time_model/features.py
touch ml/discharge_time_model/train.py
touch ml/discharge_time_model/evaluate.py
touch ml/discharge_time_model/upload.py
touch ml/discharge_time_model/requirements.txt
touch ml/discharge_time_model/README.md
```

### 2. Implement `ml/discharge_time_model/features.py`

```python
"""Feature engineering for discharge time prediction.

Extracts and encodes a feature vector from a raw encounter record.
The same logic is used at training time and inference time to guarantee
train-serve symmetry.

Design refs:
    US-036 Technical Notes — feature list, los_so_far_hours derivation
    US-036 DoD — features: admit_diagnosis_group, patient_age,
                           los_so_far_hours, pending_procedures,
                           unit, day_of_week
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd

# Categorical columns that require one-hot encoding.
CATEGORICAL_FEATURES = ["admit_diagnosis_group", "unit"]

# Numeric columns used as-is after imputation.
NUMERIC_FEATURES = [
    "patient_age",
    "los_so_far_hours",
    "pending_procedures",
    "day_of_week",  # 0=Monday … 6=Sunday
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def compute_los_so_far_hours(admit_time: datetime, reference_time: datetime | None = None) -> float:
    """Return elapsed hours since admission (float, ≥0).

    Args:
        admit_time: UTC-aware ``datetime`` of the encounter admission.
        reference_time: Reference point for elapsed time. Defaults to ``datetime.now(UTC)``.

    Returns:
        Length-of-stay so far in fractional hours.
    """
    ref = reference_time or datetime.now(timezone.utc)
    delta = ref - admit_time.replace(tzinfo=timezone.utc) if admit_time.tzinfo is None else ref - admit_time
    return max(delta.total_seconds() / 3600.0, 0.0)


def build_feature_dataframe(encounters: list[dict[str, Any]], reference_time: datetime | None = None) -> pd.DataFrame:
    """Build a feature DataFrame from a list of raw encounter dicts.

    Args:
        encounters: List of encounter dicts with at minimum the keys:
            ``admit_time``, ``patient_dob``, ``admit_diagnosis_group``,
            ``unit``, ``pending_procedures_count``, ``admit_date``.
        reference_time: Passed through to ``compute_los_so_far_hours``.

    Returns:
        ``pd.DataFrame`` with columns matching ``ALL_FEATURES``.
    """
    rows = []
    for enc in encounters:
        admit_time: datetime = enc["admit_time"]
        dob: datetime = enc["patient_dob"]
        age = math.floor((admit_time - dob).days / 365.25)

        row = {
            "patient_age": age,
            "los_so_far_hours": compute_los_so_far_hours(admit_time, reference_time),
            "pending_procedures": int(enc.get("pending_procedures_count", 0)),
            "day_of_week": admit_time.weekday(),
            "admit_diagnosis_group": str(enc.get("admit_diagnosis_group", "UNKNOWN")),
            "unit": str(enc.get("unit", "UNKNOWN")),
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=ALL_FEATURES)


def build_single_feature_vector(encounter: dict[str, Any], reference_time: datetime | None = None) -> dict[str, Any]:
    """Return a single-row dict for inference-time feature construction.

    Convenience wrapper for building a 1-row DataFrame from a single encounter.
    The returned dict is suitable for ``pd.DataFrame([result])``.
    """
    return build_feature_dataframe([encounter], reference_time).iloc[0].to_dict()
```

### 3. Implement `ml/discharge_time_model/train.py`

```python
"""Model training pipeline for discharge time prediction.

Loads encounter data from Cloud SQL, engineers features, trains a
GradientBoostingRegressor, evaluates on a 20% holdout set, and
saves the model pipeline as a joblib artefact.

Design refs:
    US-036 DoD — GradientBoostingRegressor; MAE ≤2 h; ≥80% within ±2 h
    design.md §4.1 — Scikit-learn 1.5+; joblib serialisation
    US-036 Technical Notes — model file: models/discharge_time_v1.joblib
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from features import (
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    build_feature_dataframe,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_OUTPUT_PATH = Path("models/discharge_time_v1.joblib")
RANDOM_STATE = 42


def load_training_data(db_url: str) -> tuple[pd.DataFrame, pd.Series]:
    """Query encounter table and return features + target (hours_to_discharge).

    The target is ``(actual_discharge_time - admit_time).total_seconds() / 3600``.
    Only encounters with a non-null ``discharge_time`` are used for training.

    Args:
        db_url: SQLAlchemy-compatible DB connection string (read replica preferred).

    Returns:
        Tuple of (feature DataFrame, target Series).
    """
    import sqlalchemy as sa

    engine = sa.create_engine(db_url)
    query = """
        SELECT
            admit_time,
            discharge_time,
            EXTRACT(YEAR FROM AGE(admit_time, patient_dob)) AS patient_age,
            admit_diagnosis_group,
            unit,
            pending_procedures_count,
            EXTRACT(DOW FROM admit_time) AS day_of_week
        FROM encounter
        JOIN patient ON patient.id = encounter.patient_id
        WHERE discharge_time IS NOT NULL
          AND deleted_at IS NULL
    """
    df_raw = pd.read_sql(query, engine)

    # Compute target: hours from admit_time to actual discharge_time
    df_raw["hours_to_discharge"] = (
        pd.to_datetime(df_raw["discharge_time"]) - pd.to_datetime(df_raw["admit_time"])
    ).dt.total_seconds() / 3600.0

    # Clip negative values (data quality guard)
    df_raw = df_raw[df_raw["hours_to_discharge"] >= 0].reset_index(drop=True)

    # Build feature vectors (use admit_time as reference so los_so_far_hours = 0 at training)
    # Instead, use the raw columns already extracted by SQL for training consistency
    feature_df = pd.DataFrame({
        "patient_age": df_raw["patient_age"].astype(float),
        "los_so_far_hours": 0.0,  # At admit_time, LOS = 0; model learns from snapshot features
        "pending_procedures": df_raw["pending_procedures_count"].fillna(0).astype(int),
        "day_of_week": df_raw["day_of_week"].astype(int),
        "admit_diagnosis_group": df_raw["admit_diagnosis_group"].fillna("UNKNOWN"),
        "unit": df_raw["unit"].fillna("UNKNOWN"),
    })

    target = df_raw["hours_to_discharge"]
    logger.info("Loaded %d training samples", len(feature_df))
    return feature_df, target


def build_pipeline() -> Pipeline:
    """Return an untrained Scikit-learn Pipeline.

    Preprocessing:
        - Numeric: median imputation → StandardScaler
        - Categorical: constant imputation → OneHotEncoder (handle_unknown='ignore')
    Estimator:
        - GradientBoostingRegressor (n_estimators=200, max_depth=4)
    """
    numeric_transformer = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical_transformer = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="UNKNOWN")),
        ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    preprocessor = ColumnTransformer([
        ("numeric", numeric_transformer, NUMERIC_FEATURES),
        ("categorical", categorical_transformer, CATEGORICAL_FEATURES),
    ])
    return Pipeline([
        ("preprocessor", preprocessor),
        ("regressor", GradientBoostingRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            random_state=RANDOM_STATE,
        )),
    ])


def train(db_url: str, output_path: Path = MODEL_OUTPUT_PATH) -> Path:
    """Run full training pipeline and save joblib artefact.

    Args:
        db_url: DB connection string for training data query.
        output_path: Path to write the serialised ``Pipeline`` joblib file.

    Returns:
        Resolved path of the saved model file.
    """
    X, y = load_training_data(db_url)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=RANDOM_STATE
    )
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_path)
    logger.info("Model saved → %s", output_path.resolve())
    return output_path.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train discharge time prediction model")
    parser.add_argument("--db-url", required=True, help="SQLAlchemy DB URL (read replica)")
    parser.add_argument("--output", default=str(MODEL_OUTPUT_PATH), help="Output joblib path")
    args = parser.parse_args()
    train(db_url=args.db_url, output_path=Path(args.output))
```

### 4. Implement `ml/discharge_time_model/evaluate.py`

```python
"""Model evaluation — MAE, RMSE, and percentage within ±2 hours.

Design refs:
    US-036 AC Scenario 2 — ≥80% predictions within ±2 h; MAE ≤2 h
    US-036 DoD           — evaluation metrics must be logged and gated
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

logger = logging.getLogger(__name__)

QUALITY_GATE_MAE_HOURS = 2.0
QUALITY_GATE_WITHIN_2H_PCT = 0.80


class EvaluationResult(NamedTuple):
    mae_hours: float
    rmse_hours: float
    pct_within_2h: float
    passed: bool


def evaluate(pipeline_path: Path, X_test: pd.DataFrame, y_test: pd.Series) -> EvaluationResult:
    """Load the serialised pipeline and evaluate on the provided holdout set.

    Raises:
        SystemExit: If quality gates are not met (CI gate behaviour).

    Returns:
        ``EvaluationResult`` with computed metrics.
    """
    pipeline = joblib.load(pipeline_path)
    y_pred = pipeline.predict(X_test)

    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(root_mean_squared_error(y_test, y_pred))
    within_2h = float(np.mean(np.abs(y_pred - y_test.to_numpy()) <= 2.0))

    result = EvaluationResult(
        mae_hours=mae,
        rmse_hours=rmse,
        pct_within_2h=within_2h,
        passed=(mae <= QUALITY_GATE_MAE_HOURS and within_2h >= QUALITY_GATE_WITHIN_2H_PCT),
    )

    logger.info("Evaluation — MAE: %.2f h | RMSE: %.2f h | Within ±2h: %.1f%%",
                mae, rmse, within_2h * 100)

    if not result.passed:
        logger.error(
            "QUALITY GATE FAILED — MAE=%.2f (threshold %.1f) | Within±2h=%.1f%% (threshold %.0f%%)",
            mae, QUALITY_GATE_MAE_HOURS, within_2h * 100, QUALITY_GATE_WITHIN_2H_PCT * 100,
        )
        raise SystemExit(1)

    return result
```

### 5. Implement `ml/discharge_time_model/upload.py`

```python
"""Upload trained model artefact to GCS ml-models bucket with version tag.

Design refs:
    US-036 DoD — model stored in GCS ml-models bucket with version tag
    US-036 Technical Notes — model file: models/discharge_time_v1.joblib
"""
from __future__ import annotations

import logging
from pathlib import Path

from google.cloud import storage

logger = logging.getLogger(__name__)

GCS_BUCKET = "ml-models"
GCS_OBJECT_PREFIX = "discharge_time"


def upload_model(local_path: Path, version_tag: str, bucket_name: str = GCS_BUCKET) -> str:
    """Upload the model file to GCS and return the GCS URI.

    The object is uploaded to two paths:
    - ``discharge_time/{version_tag}/discharge_time.joblib`` (versioned)
    - ``discharge_time/latest/discharge_time.joblib`` (inference service pointer)

    Args:
        local_path: Path to the local ``joblib`` file.
        version_tag: Semantic version string, e.g. ``"v1"`` or ``"v20260717"``.
        bucket_name: GCS bucket name (default: ``ml-models``).

    Returns:
        GCS URI of the versioned upload.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    versioned_blob_name = f"{GCS_OBJECT_PREFIX}/{version_tag}/discharge_time.joblib"
    latest_blob_name = f"{GCS_OBJECT_PREFIX}/latest/discharge_time.joblib"

    for blob_name in (versioned_blob_name, latest_blob_name):
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local_path))
        logger.info("Uploaded → gs://%s/%s", bucket_name, blob_name)

    gcs_uri = f"gs://{bucket_name}/{versioned_blob_name}"
    logger.info("Model artefact available at: %s", gcs_uri)
    return gcs_uri
```

### 6. Add `ml/discharge_time_model/requirements.txt`

```
scikit-learn>=1.5.0
pandas>=2.0.0
numpy>=1.26.0
joblib>=1.3.0
sqlalchemy>=2.0.0
google-cloud-storage>=2.14.0
psycopg2-binary>=2.9.0
```

### 7. Add CI/CD nightly retrain step to Cloud Build pipeline

In `.propel/context/devops/cicd-spec.md` (note only — implementation in `/create-pipeline-scripts`):

```yaml
# Nightly retrain (Cloud Build scheduled trigger):
steps:
  - name: 'python:3.12-slim'
    entrypoint: bash
    args:
      - '-c'
      - |
        pip install -r ml/discharge_time_model/requirements.txt
        python ml/discharge_time_model/train.py \
          --db-url $$DB_READ_URL \
          --output models/discharge_time_v1.joblib
        python -c "
        from ml.discharge_time_model.upload import upload_model
        from pathlib import Path
        import datetime
        tag = 'v' + datetime.date.today().strftime('%Y%m%d')
        upload_model(Path('models/discharge_time_v1.joblib'), tag)
        "
    secretEnv: ['DB_READ_URL']
```

---

## Validation Checklist

- [ ] Training script runs end-to-end against dev Cloud SQL read replica without errors
- [ ] Evaluation: MAE ≤ 2.0 hours on 20% holdout set
- [ ] Evaluation: ≥ 80% predictions fall within ±2 hours of actual discharge
- [ ] `models/discharge_time_v1.joblib` saved locally and verifiable via `joblib.load()`
- [ ] Model uploaded to `gs://ml-models/discharge_time/v1/discharge_time.joblib`
- [ ] `gs://ml-models/discharge_time/latest/discharge_time.joblib` points to current version
- [ ] `evaluate.py` exits with code 1 if quality gates are not met (CI gate verified)
- [ ] No PHI fields (patient name, DOB, MRN) present in feature vectors or model artefact metadata

---

## Definition of Done Checklist (US-036)

| Item | Status |
|------|--------|
| ✅ Model training pipeline: Jupyter/Python with feature engineering, training, evaluation | This task |
| ✅ Features: admit_diagnosis_group, patient_age, los_so_far_hours, pending_procedures, unit, day_of_week | This task |
| ✅ Model evaluation: MAE, RMSE, % within ±2 h on holdout (≥80% threshold) | This task |
| ✅ Model versioning: model stored in GCS with version tag | This task |
