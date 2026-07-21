---
id: TASK-001
title: "Author `cloudbuild-shared.yaml` — Shared Lint and Unit Test Steps"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: CI/CD
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: []
---

# TASK-001: Author `cloudbuild-shared.yaml` — Shared Lint and Unit Test Steps

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** CI/CD | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-003 requires a multi-stage CI/CD pipeline. The technical notes specify that shared steps be extracted into a `cloudbuild-shared.yaml` to avoid duplication across per-service `cloudbuild.yaml` files (DRY). This shared file provides the **lint** and **unit test** stages that every service must pass before container build begins.

The pipeline gate order is: `lint → unit tests → container build → vulnerability scan → canary deploy → full promotion`. This task delivers the first two stages.

---

## Acceptance Criteria Addressed

| US-003 AC | Requirement |
|---|---|
| **Scenario 1** | Pipeline executes stages in order: lint → unit tests → … each stage gates the next on success |
| **Scenario 4** | No plaintext secrets appear in any log line — lint and test steps must not echo environment variables containing secrets |

---

## Implementation Steps

### 1. Create `cloudbuild-shared.yaml` at Repository Root

Create the file at `cloudbuild-shared.yaml` (or at `.cloudbuild/cloudbuild-shared.yaml` if a `.cloudbuild/` directory is used for organisation). This file is referenced by `cloudbuild.yaml` via the `--config` flag on the `gcloud builds submit` call or via Cloud Build's included-files pattern.

The shared file defines two ordered step groups:

#### Stage 1 — Lint

```yaml
steps:
  # --- Stage 1: Lint ---
  - name: 'python:3.11-slim'
    id: 'lint-python'
    entrypoint: bash
    args:
      - '-c'
      - |
        pip install flake8 --quiet
        flake8 src/ --max-line-length=120 --statistics
    dir: '${_SERVICE_DIR}'

  - name: 'node:20-slim'
    id: 'lint-js'
    entrypoint: bash
    args:
      - '-c'
      - |
        npm ci --silent
        npx eslint src/ --ext .js,.ts --max-warnings=0
    dir: '${_SERVICE_DIR}'
    waitFor: ['lint-python']
```

**Note:** Each service sets `_SERVICE_DIR` substitution in its own `cloudbuild.yaml` (e.g., `services/api-gateway`). Steps that do not apply to a given service runtime are skipped via a guard condition (see TASK-002 for the conditional pattern).

#### Stage 2 — Unit Tests

```yaml
  # --- Stage 2: Unit Tests ---
  - name: 'python:3.11-slim'
    id: 'test-python'
    entrypoint: bash
    args:
      - '-c'
      - |
        pip install pytest pytest-cov --quiet -r requirements.txt
        pytest tests/ --cov=src/ --cov-report=term-missing --tb=short
    dir: '${_SERVICE_DIR}'
    waitFor: ['lint-python', 'lint-js']

  - name: 'node:20-slim'
    id: 'test-js'
    entrypoint: bash
    args:
      - '-c'
      - |
        npm ci --silent
        npx jest --coverage --ci
    dir: '${_SERVICE_DIR}'
    waitFor: ['lint-python', 'lint-js']
```

### 2. Define Required Substitutions

Add a `substitutions` block listing every variable that calling `cloudbuild.yaml` files must supply:

```yaml
substitutions:
  _SERVICE_DIR: '.'          # Override per service
  _SERVICE_NAME: 'undefined' # e.g., api-gateway
  _ENVIRONMENT: 'dev'        # dev | staging | prod
```

### 3. Define `options` Block

```yaml
options:
  logging: CLOUD_LOGGING_ONLY  # Prevents log streaming to stdout; reduces risk of secret leakage
  machineType: 'E2_HIGHCPU_8'
  substitution_option: 'ALLOW_LOOSE'
```

`CLOUD_LOGGING_ONLY` routes all output to Cloud Logging (not stdout), which satisfies Scenario 4 by ensuring no step output is printed directly to the terminal where an operator might inadvertently echo a substitution.

### 4. Secret Safety Rules for All Steps

- **Never** pass `--env` with a value sourced from a `$SECRET` environment variable in a lint or test step.
- Lint and test steps must not require any runtime secret access. If a test requires a database, use an in-memory SQLite or mock.
- Verify no step uses `echo $VARIABLE` where VARIABLE could expand to a secret value.

---

## Acceptance Test

Run the following to confirm the shared config is syntactically valid before wiring it into per-service pipelines:

```bash
gcloud builds submit --no-source --config=cloudbuild-shared.yaml \
  --substitutions=_SERVICE_DIR=services/api-gateway,_SERVICE_NAME=api-gateway,_ENVIRONMENT=dev \
  --dry-run
```

Expected: exit code `0` with zero errors.

---

## Files Produced

| File | Action |
|---|---|
| `cloudbuild-shared.yaml` (or `.cloudbuild/cloudbuild-shared.yaml`) | Create |

---

## Definition of Done Checklist

- [ ] `cloudbuild-shared.yaml` created with lint (flake8 + eslint) and unit test (pytest + jest) steps
- [ ] `CLOUD_LOGGING_ONLY` option set — no stdout streaming
- [ ] Required substitutions documented in the file header comment
- [ ] `--dry-run` validation passes with exit code `0`
- [ ] No step echoes or exposes secret-shaped substitution values
