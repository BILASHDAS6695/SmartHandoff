---
id: TASK-007
title: "Code Review & DoD Sign-off — US-039 30-Day Readmission Risk Score at Discharge"
user_story: US-039
epic: EP-007
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Security Engineer
upstream: [US-039/TASK-001, US-039/TASK-002, US-039/TASK-003, US-039/TASK-004, US-039/TASK-005, US-039/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-039 30-Day Readmission Risk Score at Discharge

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-039. It verifies that all implementation tasks (TASK-001 through TASK-006) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to three high-risk surfaces:

### 1. PHI in LLM/ML prompts and logs (HIPAA / BR-020, AIR-021)

The `FollowUpCareAgent` sends numeric feature vectors to the ML Inference Service (no PHI in feature values — age, LOS, comorbidity count are clinical stats, not identifiers). Confirm:

- **Feature extraction logs** (`feature_extractor.py`) include only `encounter_id` (UUID) and feature values — no patient name, MRN, DOB, phone, or email.
- **ML Inference Service logs** include only `risk_score`, `risk_tier`, feature values — no `encounter_id` or patient identifiers in the inference service itself (it receives only a feature vector, not a patient identifier).
- **`FollowUpCareAgent` logs** include only `encounter_id` (UUID), `risk_score`, `risk_tier`, `model_version` — never PHI.
- **`GET /api/v1/encounters/{id}/risk` response** returns only `encounter_id` (UUID), numeric `risk_score`, `risk_tier`, `contributing_factors` (numeric SHAP values + labels), `model_version`, `assessed_at` — no patient name or MRN.
- Confirm Cloud Logging excludes any field named `mrn`, `first_name`, `last_name`, `dob` from the `followup-agent` and `ml-inference` log sinks.

### 2. ML model quality gate and training data integrity (patient safety)

Inaccurate risk scores could result in under-resourced follow-up for high-risk patients — a patient safety concern.

- `train_readmission_risk.py` CI quality gate (`MIN_AUC_THRESHOLD = 0.80`) is active and raises `ValueError` (non-zero exit) if AUC < 0.80.
- Cloud Build step rejects the model artifact if the training script exits non-zero.
- `evaluation_report.json` is uploaded to GCS alongside `model.joblib` — confirm report is human-readable and includes `n_train`, `n_test`, `readmission_rate_train`, `readmission_rate_test`.
- Model artifact is stored under a versioned GCS path (`ml-models/readmission-risk/v{N}/`) — old versions are retained (DR-014: 3 versions retained).
- Risk tier thresholds (`LOW < 0.30`, `MEDIUM 0.30–0.70`, `HIGH ≥ 0.70`) are implemented in exactly one place: `assign_risk_tier()` in `ml-inference/app/schemas.py` — no duplication in `agent.py` or the API router.

### 3. RBAC enforcement on the Risk API (SEC-002 / design.md §8.3)

- `GET /api/v1/encounters/{id}/risk` returns HTTP 403 for `pharmacist` and `patient` roles.
- `GET /api/v1/encounters/{id}/risk` returns HTTP 403 for a nurse accessing an encounter outside their assigned unit (unit-scoped enforcement).
- `require_any_role({"admin", "physician", "nurse"})` is applied as a FastAPI dependency at the router level.
- Confirm that the `patient` JWT scope cannot be used to access any encounter other than the encounter-scoped one.

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# -----------------------------------------------------------------------
# 1. Syntax check — all new modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
targets = [
    # ML Inference Service
    'ml-inference/app/__init__.py',
    'ml-inference/app/schemas.py',
    'ml-inference/app/model_loader.py',
    'ml-inference/app/predictor.py',
    'ml-inference/app/routers/predict.py',
    'ml-inference/app/main.py',
    # Training
    'ml-inference/training/feature_schema.py',
    'ml-inference/training/generate_synthetic_data.py',
    'ml-inference/training/train_readmission_risk.py',
    # Follow-up Care Agent
    'backend/app/agents/followup_care/__init__.py',
    'backend/app/agents/followup_care/schemas.py',
    'backend/app/agents/followup_care/feature_extractor.py',
    'backend/app/agents/followup_care/inference_client.py',
    'backend/app/agents/followup_care/agent.py',
    'backend/app/agents/followup_care/main.py',
    # API Gateway
    'api-gateway/app/schemas/risk.py',
    'api-gateway/app/routers/encounters_risk.py',
]
for p in targets:
    path = pathlib.Path(p)
    if path.suffix == '.py' and path.exists():
        ast.parse(path.read_text())
        print(f'OK  {p}')
    else:
        print(f'SKIP {p}')
"

# -----------------------------------------------------------------------
# 2. Run training pipeline with synthetic data (validates AUC quality gate)
# -----------------------------------------------------------------------
cd ml-inference
python -m training.generate_synthetic_data --output data/synthetic_encounters.csv --n 5000
python -m training.train_readmission_risk \
    --source csv --data data/synthetic_encounters.csv --output models/
echo "Training exit code: $?"
cat models/evaluation_report.json

# -----------------------------------------------------------------------
# 3. Run all unit tests
# -----------------------------------------------------------------------
# ML Inference Service tests
cd ml-inference
pytest tests/unit/ -v --cov=app --cov=training --cov-report=term-missing

# Follow-up Care Agent tests
cd backend
pytest tests/unit/agents/followup_care/ -v --cov=app/agents/followup_care --cov-report=term-missing

# API Gateway risk endpoint tests
cd api-gateway
pytest tests/unit/routers/test_encounters_risk_router.py -v \
    --cov=app/routers/encounters_risk --cov-report=term-missing

# -----------------------------------------------------------------------
# 4. Static analysis (SAST) — bandit on new files
# -----------------------------------------------------------------------
bandit -r ml-inference/app/ ml-inference/training/ \
       backend/app/agents/followup_care/ \
       api-gateway/app/schemas/risk.py \
       api-gateway/app/routers/encounters_risk.py \
       -ll -x ml-inference/tests/

# -----------------------------------------------------------------------
# 5. Dependency audit
# -----------------------------------------------------------------------
pip-audit -r ml-inference/requirements.txt
```

---

## Code Review Checklist

### Security (Security Engineer sign-off required)

- [ ] No PHI in `feature_extractor.py` log lines — only `encounter_id` UUID and numeric feature values
- [ ] No PHI in `agent.py` log lines — only `encounter_id`, `risk_score`, `risk_tier`, `model_version`
- [ ] No patient identifiers in `ml-inference/app/predictor.py` log lines — inference receives only feature vector
- [ ] `GET /api/v1/encounters/{id}/risk` response contains no patient name, MRN, or DOB
- [ ] `require_any_role({"admin", "physician", "nurse"})` applied as router-level dependency (not in handler body)
- [ ] Pharmacist and patient JWTs receive HTTP 403 (verified by unit tests)
- [ ] `assign_risk_tier()` is the single source of truth — not duplicated in `agent.py`, `feature_extractor.py`, or the API router
- [ ] `ML_MODEL_GCS_URI` and `ML_MODEL_VERSION` are sourced from Secret Manager / env vars (not hardcoded)
- [ ] No hardcoded secrets in any new file

### ML Quality

- [ ] `MIN_AUC_THRESHOLD = 0.80` is enforced in `train_readmission_risk.py` and exits non-zero if not met
- [ ] `evaluation_report.json` uploaded to GCS alongside `model.joblib` and `scaler.joblib`
- [ ] GCS path follows `ml-models/readmission-risk/v{N}/` versioned convention (DR-014)
- [ ] `class_weight="balanced"` is set on `LogisticRegression` to handle ~20% readmission base rate
- [ ] `StandardScaler` fitted on train set only (not fit on test set — no data leakage)
- [ ] SHAP `LinearExplainer` is initialised once and cached (`_shap_explainer` singleton)

### Correctness

- [ ] `FollowUpCareAgent` only processes A03 events; A01, A02 skipped silently (returns `None`)
- [ ] Feature extraction uses `admit_date` reference for age calculation (not current date)
- [ ] `num_prior_admissions_12mo` query excludes the current encounter (`Encounter.id != encounter.id`)
- [ ] `encounter.risk_score` and `encounter.risk_tier` written in a single atomic `UPDATE` statement
- [ ] `AgentTask.output_summary` is stored as JSON string (for `GET /risk` to parse `contributing_factors`)
- [ ] FHIR `get_conditions()` failure falls back to `num_comorbidities=0.0` with WARNING (not ERROR / not crash)
- [ ] `assign_risk_tier(0.30)` returns `MEDIUM` (0.30 is inclusive of MEDIUM boundary)
- [ ] `assign_risk_tier(0.70)` returns `HIGH` (0.70 is inclusive of HIGH boundary)
- [ ] ML Inference Service `/ready` probe returns HTTP 503 if model not loaded at startup

### Performance

- [ ] Model and scaler loaded once at startup in `model_loader.py` — no per-request GCS/disk I/O
- [ ] SHAP `LinearExplainer` initialised once and cached — no re-instantiation per request
- [ ] Inference endpoint p95 latency < 500ms verified (benchmarked locally or in staging)
- [ ] `followup-agent` Cloud Run min-instances=1 to avoid cold-start latency (design.md §9.2)

### Code Quality

- [ ] `assign_risk_tier()` has comprehensive docstring with threshold values
- [ ] `feature_extractor.py` has clear comments explaining each feature source (FHIR vs. DB)
- [ ] `inference_client.py` retry logic uses exponential backoff (1s, 2s, 4s) matching AIR-011
- [ ] `FollowUpCareAgent` docstring references design.md §3.1, §3.2, §9.2
- [ ] All new files have `from __future__ import annotations` for forward reference support
- [ ] No unused imports in any new file

---

## Definition of Done — Final Checklist

| Requirement | Task | Status |
|-------------|------|--------|
| `FollowUpCareAgent` extends `BaseAgent`; triggered by A03 | TASK-004 | [ ] |
| `POST /ml-inference/predict/readmission` endpoint | TASK-002 | [ ] |
| 7 features assembled from FHIR + DB | TASK-004 | [ ] |
| Risk tier thresholds: LOW <0.30, MEDIUM 0.30–0.70, HIGH ≥0.70 | TASK-002, TASK-005 | [ ] |
| `encounter.risk_score` and `encounter.risk_tier` persisted | TASK-004 | [ ] |
| `GET /api/v1/encounters/{id}/risk` with `contributing_factors` | TASK-005 | [ ] |
| AUC quality gate ≥0.80; evaluation report in GCS | TASK-001 | [ ] |
| `config/feature_labels.yaml` with all 7 labels | TASK-003 | [ ] |
| Unit tests (≥80% branch coverage) | TASK-006 | [ ] |
| Security review sign-off (PHI, RBAC, model quality) | TASK-007 | [ ] |
| Code peer-reviewed and approved | TASK-007 | [ ] |
