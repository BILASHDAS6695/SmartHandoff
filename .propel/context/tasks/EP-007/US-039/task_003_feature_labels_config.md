---
id: TASK-003
title: "config/feature_labels.yaml — SHAP Feature Label Mapping"
user_story: US-039
epic: EP-007
sprint: 2
layer: Configuration
estimate: 0.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-039/TASK-002]
---

# TASK-003: config/feature_labels.yaml — SHAP Feature Label Mapping

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Configuration | **Est:** 0.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039 Technical Notes specify: *"map to human-readable labels in `config/feature_labels.yaml`"* for SHAP contributing factors returned by the inference endpoint (AC Scenario 4).

This task creates the YAML configuration file that maps raw Scikit-learn feature names (from `training.feature_schema.FEATURE_NAMES`) to clinically meaningful labels displayed to care managers, and documents the ordinal encoding for `discharge_disposition` and `primary_diagnosis_group` categorical features.

The `predictor.py` in TASK-002 reads this file via `app.state.feature_labels` (loaded at startup in `main.py`).

**Design references:**
- US-039 Technical Notes — `config/feature_labels.yaml`; SHAP contributing_factors mapped to human-readable labels
- US-039 AC Scenario 4 — `contributing_factors` returned as human-readable labels

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | `contributing_factors` returns top-5 features as human-readable labels (e.g. "Number of Prior Admissions (12 months)" instead of `num_prior_admissions_12mo`) |

---

## Implementation Steps

### 1. Create `ml-inference/config/feature_labels.yaml`

```yaml
# SmartHandoff ML Inference Service — Feature Label Mapping
# Maps raw feature names (training.feature_schema.FEATURE_NAMES) to
# clinician-friendly labels for SHAP contributing_factors API output.
#
# US-039 Technical Notes: "map to human-readable labels in config/feature_labels.yaml"
# US-039 AC Scenario 4:   contributing_factors returned with human-readable feature names

feature_labels:
  age: "Patient Age (Years)"
  los_days: "Length of Stay (Days)"
  num_comorbidities: "Number of Active Comorbidities"
  num_prior_admissions_12mo: "Prior Hospital Admissions (12 Months)"
  medication_count: "Active Medication Count at Discharge"
  discharge_disposition: "Discharge Destination"
  primary_diagnosis_group: "Primary Diagnosis Category"

# Ordinal encoding reference — for documentation and future UI display
# NOT used by predictor.py (values are encoded integers passed in the feature vector)
discharge_disposition_encoding:
  0: "Home / Self-Care"
  1: "Skilled Nursing Facility (SNF)"
  2: "Inpatient Rehabilitation Facility"
  3: "Home with Home Health Services"
  4: "Against Medical Advice (AMA)"

# Primary diagnosis group encoding — 20 groups aligned with CMS MS-DRG major categories
# Populated by the data engineering team during model training data preparation
primary_diagnosis_group_encoding:
  0: "Circulatory System Disorders"
  1: "Respiratory System Disorders"
  2: "Musculoskeletal & Connective Tissue"
  3: "Nervous System Disorders"
  4: "Digestive System Disorders"
  5: "Endocrine, Nutritional & Metabolic"
  6: "Genitourinary System Disorders"
  7: "Infectious & Parasitic Diseases"
  8: "Neoplasms"
  9: "Mental Health & Substance Use"
  10: "Injuries, Poisoning & Toxic Effects"
  11: "Factors Influencing Health Status"
  12: "Skin, Subcutaneous Tissue & Breast"
  13: "Blood & Blood-Forming Organs"
  14: "Hepatobiliary & Pancreatic Disorders"
  15: "Kidney & Urinary Tract Disorders"
  16: "Female Reproductive System Disorders"
  17: "Male Reproductive System Disorders"
  18: "Burns"
  19: "Other"
```

### 2. Add config directory to `.dockerignore` exclusions (keep in image)

Confirm `config/` is NOT in `ml-inference/.dockerignore` — the YAML must be present at runtime.

```
# ml-inference/.dockerignore
__pycache__/
*.pyc
*.pyo
.pytest_cache/
tests/
data/
models/
.env
```

### 3. Add schema validation for feature_labels.yaml at startup (in `main.py`)

Add a validation call in the `lifespan()` function after loading the YAML to ensure all required keys are present:

```python
# In ml-inference/app/main.py — inside lifespan(), after loading feature_labels
from training.feature_schema import FEATURE_NAMES

missing = [f for f in FEATURE_NAMES if f not in app.state.feature_labels["feature_labels"]]
if missing:
    raise RuntimeError(
        f"config/feature_labels.yaml is missing labels for features: {missing}. "
        "All FEATURE_NAMES must have a corresponding entry."
    )
logger.info("Feature labels validated — all %d features present.", len(FEATURE_NAMES))
```

> **Note:** The `predictor.py` lookup uses `feature_labels.get(feature_name, feature_name)` as a safe fallback, but startup validation catches configuration drift early.

---

## File Checklist

| File | Action |
|------|--------|
| `ml-inference/config/feature_labels.yaml` | Create |
| `ml-inference/.dockerignore` | Create |
| `ml-inference/app/main.py` | Update — add startup validation of feature_labels.yaml keys |

---

## Validation

- [ ] `feature_labels.yaml` contains all 7 keys matching `FEATURE_NAMES` in `training.feature_schema`
- [ ] `discharge_disposition_encoding` covers values 0–4 (all 5 disposition categories)
- [ ] `primary_diagnosis_group_encoding` covers values 0–19 (all 20 groups)
- [ ] Startup validation in `main.py` raises `RuntimeError` if a feature name is missing from YAML
- [ ] `POST /ml-inference/predict/readmission` response `contributing_factors[].feature` contains the YAML label (e.g. `"Prior Hospital Admissions (12 Months)"`) not the raw feature name (`num_prior_admissions_12mo`)

---

## Definition of Done

- [ ] `config/feature_labels.yaml` created with all 7 feature labels
- [ ] Discharge disposition and diagnosis group ordinal encodings documented in YAML
- [ ] Startup validation added to `main.py` lifespan to catch missing labels at service boot
- [ ] `.dockerignore` confirms `config/` is included in the Docker image
- [ ] Code peer-reviewed before merge
