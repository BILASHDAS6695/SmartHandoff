---
id: TASK-007
title: "Code Review & DoD Sign-off — US-036 Predict Patient Discharge Time with ML Model"
user_story: US-036
epic: EP-006
sprint: 2
layer: Process
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Security Engineer
upstream: [US-036/TASK-001, US-036/TASK-002, US-036/TASK-003, US-036/TASK-004, US-036/TASK-005, US-036/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-036 Predict Patient Discharge Time with ML Model

> **Story:** US-036 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Process | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-036. It verifies that all implementation tasks (TASK-001 through TASK-006) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to three high-risk surfaces:

### 1. PHI containment in ML pipeline and inference service (HIPAA / BR-020)

PHI fields (`patient_dob`) flow from the encounter record into the inference service request payload. Confirm:

- **`DischargePredictionService` logs** include only `encounter_id` (UUID), confidence level, and predicted datetime — no `patient_dob`, `patient_name`, or `mrn`.
- **`ML Inference Service` logs** include only `encounter_id` and prediction summary — the `patient_dob` in the request body is never echoed to logs.
- **Training pipeline** uses only de-identified derived features (`patient_age`, `los_so_far_hours`, etc.) — the raw DOB column is transformed and not included in the model artefact or training logs.
- **`ml-models` GCS bucket** is CMEK-encrypted and has no public IAM binding — model files do not contain PHI.
- **Cloud Build pipeline** (nightly retrain) accesses the read replica over VPC-private connection — DB credentials are sourced from Secret Manager, not hardcoded.

### 2. Service account JWT authentication on ML Inference Service (SEC-001 / SEC-010)

- **`POST /ml-inference/predict/discharge-time`** requires a valid Google-signed service account JWT (`verify_service_account_jwt` dependency).
- Unauthenticated requests return HTTP 401 with `WWW-Authenticate: Bearer` — no 200 bypass possible.
- The ML Inference Service Cloud Run service has **no public ingress** — only internal VPC traffic from `bed-mgmt-agent` is permitted (confirmed via Terraform `ingress = "internal"` setting).
- `ML_INFERENCE_AUDIENCE` env var is set correctly at deploy time to prevent token reuse attacks.
- The `_certs_cache` in `auth.py` is populated at startup (not per-request) to avoid JWKS DoS.

### 3. ML model quality gate enforcement in CI/CD (AI/ML risk — AR-009)

- `evaluate.py` exits with code 1 if MAE > 2.0 h or % within ±2 h < 80% — CI must fail the pipeline on gate breach.
- The nightly retrain Cloud Build step does NOT deploy a failing model to the `latest` GCS pointer.
- Model version tag is immutable once uploaded — overwriting a versioned artefact is prohibited by GCS retention policy.
- Model drift monitoring alert is configured in Cloud Monitoring (AR-009 mitigation): alert fires when monthly prediction MAE exceeds 2.5 h.

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# 1. Python linting and security scan
cd ml_inference && ruff check app/ && bandit -r app/ -ll
cd backend && ruff check app/agents/bed_management/ && bandit -r app/agents/bed_management/prediction_service.py -ll

# 2. Unit tests with coverage
pytest ml_inference/tests/ ml/discharge_time_model/tests/ \
  backend/tests/unit/agents/bed_management/test_prediction_service.py \
  -v --cov=app --cov-report=term-missing

# 3. ML model evaluation quality gate (must not exit 1)
python ml/discharge_time_model/evaluate.py

# 4. DB migration — dry run on dev
cd backend && alembic upgrade head --sql | head -40
alembic upgrade head

# 5. Angular build — no errors
cd frontend && ng build --configuration production

# 6. Container build — no CRITICAL CVEs
cd ml_inference && docker build -t ml-inference:review .
# Scan (Artifact Registry scan or local trivy):
# trivy image ml-inference:review --exit-code 1 --severity CRITICAL

# 7. axe-core accessibility
npx axe-core --url http://localhost:4200/beds
```

---

## Code Review Checklist

### Backend / ML Inference Service

- [ ] `verify_service_account_jwt` dependency applied at router level (not only in handler body)
- [ ] `POST /ml-inference/predict/discharge-time` returns 401 for missing token (not 422)
- [ ] Model pre-loaded at startup — `GET /ready` returns 503 until model is cached
- [ ] `_MODEL_CACHE` module-level dict prevents per-request GCS download (TR-007)
- [ ] Confidence level thresholds match spec: high <1 h, medium 1-2 h, low >2 h (US-036 Technical Notes)
- [ ] `patient_dob` not echoed in any log record in `discharge_time.py` router
- [ ] `Dockerfile` uses `python:3.12-slim` base image (TR-019)
- [ ] `uvicorn --workers 2` in CMD (concurrency 50 per Cloud Run instance spec)

### Backend / DischargePredictionService

- [ ] `update_prediction` called outside the main bed-status transaction (prediction failure must not roll back bed status)
- [ ] Exponential backoff: 3 attempts with delays 1 s, 2 s (AIR-011)
- [ ] `patient_dob` does NOT appear in any log record
- [ ] Returns `False` on exhausted retries — does not raise (agent resilience)
- [ ] `ML_INFERENCE_SERVICE_URL` missing → WARNING log + prediction skipped (no crash)
- [ ] `BedBoardRefreshService.refresh_async()` called after successful DB write (AC Scenario 3 — 60 s window)

### Database Migration

- [ ] `alembic upgrade head` and `alembic downgrade -1` both complete cleanly on dev
- [ ] `predicted_discharge_time` column is nullable (initial state before first prediction)
- [ ] `mv_bed_board` recreated with prediction columns; unique index `uix_mv_bed_board_bed_id` intact
- [ ] Partial index on `encounter.predicted_discharge_time` created (WHERE status = 'ADMITTED')
- [ ] No PHI columns added (prediction datetime and confidence level are not patient identifiers)

### ML Training Pipeline

- [ ] Quality gate enforced: `evaluate.py` exits 1 on MAE > 2.0 h or <80% within ±2 h
- [ ] `build_pipeline()` in `train.py` and feature vector in `routers/discharge_time.py` use identical feature names and order (train-serve symmetry)
- [ ] `patient_dob` not stored in model artefact or training logs — only derived `patient_age`
- [ ] `upload_model()` uploads to both versioned and `latest` paths in GCS

### Frontend

- [ ] `DischargeWindowComponent` renders correctly with `null` prediction (shows "Predicting…")
- [ ] Confidence chip includes text label — colour is not the sole indicator (WCAG 1.4.1)
- [ ] `role="status"` on `.discharge-window` div (live region)
- [ ] `@if (bed.bedStatus === 'OCCUPIED')` guard — no widget rendered for VACANT/DIRTY beds
- [ ] `ng lint` passes with no WCAG violations from `@angular-eslint/accessibility`

### Security Sign-off

- [ ] PHI audit confirmed: `patient_dob` flows only API request body → inference → discarded; never logged on either side
- [ ] ML Inference Cloud Run ingress = `internal` (VPC only — no public internet access)
- [ ] `ml-models` GCS bucket IAM: read access scoped to `bed-mgmt-agent` service account and `ml-inference` service account only
- [ ] Cloud Build nightly retrain job does NOT deploy model to `latest` if quality gate exits 1

---

## Definition of Done — Final Checklist

| DoD Item | Task | Status |
|----------|------|--------|
| ML Inference Service Cloud Run: serves GradientBoostingRegressor via joblib | TASK-002 | |
| Model training pipeline with feature engineering, training, evaluation | TASK-001 | |
| Features: admit_diagnosis_group, patient_age, los_so_far_hours, pending_procedures, unit, day_of_week | TASK-001 | |
| Model evaluation: MAE, RMSE, % within ±2 h on holdout (≥80% threshold) | TASK-001 | |
| `POST /ml-inference/predict/discharge-time` FastAPI endpoint (auth: service account JWT) | TASK-002 | |
| Prediction stored in `encounter.predicted_discharge_time` and reflected in `mv_bed_board` | TASK-003 + TASK-004 | |
| Model versioning: model stored in GCS with version tag | TASK-001 | |
| Inference service loads latest model on startup | TASK-002 | |
| Prediction displayed on bed board with colour-coded confidence indicator | TASK-005 | |
| Unit tests: inference endpoint, feature vector construction | TASK-006 | |
| Prediction updates within 60 s of status change (AC Scenario 3) | TASK-004 | |
| Code reviewed and approved | This task | |

---

## Reviewer Sign-off

| Role | Name | Date | Sign-off |
|------|------|------|----------|
| AI/ML Engineer | | | ☐ |
| Security Engineer | | | ☐ |
| Tech Lead | | | ☐ |
