---
task_id: task_003
story_id: us_002
epic: EP-TECH
title: Cloud Build Pipeline YAML — Lint, Test, Build, and Push Steps
layer: CI/CD
effort_hours: 2.5
sequence: 3
status: Draft
---

# TASK-003: Cloud Build Pipeline YAML — Lint, Test, Build, and Push Steps

> **Story:** EP-TECH/US-002 | **Layer:** CI/CD | **Effort:** 2.5 hours | **Seq:** 3 of 7

## Objective

Write the main Cloud Build pipeline YAML (`.cloudbuild/build.yaml`) that executes on every push to `main`: Python linting (ruff + bandit), TypeScript/Angular linting (eslint), unit tests with ≥80% coverage gate, Docker image builds for all changed services, and pushes to Artifact Registry.

## Implementation Steps

### 1. Main CI Pipeline (`.cloudbuild/build.yaml`)

```yaml
# ─────────────────────────────────────────────────────────────────────
# SmartHandoff — Main CI Pipeline
# Triggers on: push to main branch (all service directories)
# Steps: lint → test → build → push → vulnerability scan → deploy
# ─────────────────────────────────────────────────────────────────────
substitutions:
  _REGION: us-central1
  _REGISTRY: us-central1-docker.pkg.dev
  _PROJECT_ID: ${PROJECT_ID}
  _ENVIRONMENT: staging
  _SHORT_SHA: ${SHORT_SHA}

options:
  logging: CLOUD_LOGGING_ONLY
  machineType: E2_HIGHCPU_8
  dynamic_substitutions: true

steps:

# ──────────────────────────────────────────
# STEP 1: Python Linting — ruff + bandit
# ──────────────────────────────────────────
- id: python-lint-ruff
  name: ghcr.io/astral-sh/ruff:latest
  args: ['check', '--output-format=github', 'services/']
  waitFor: ['-']  # Start immediately (parallel with other lint steps)

- id: python-sast-bandit
  name: python:3.12-slim
  entrypoint: sh
  args:
    - -c
    - |
      pip install bandit[toml] --quiet
      bandit -r services/ \
        --severity-level HIGH \
        --confidence-level HIGH \
        --format txt \
        --exclude services/*/tests/
  waitFor: ['-']

- id: python-deps-audit
  name: python:3.12-slim
  entrypoint: sh
  args:
    - -c
    - |
      pip install pip-audit --quiet
      pip-audit --requirement services/api-gateway/requirements.txt \
                --requirement services/hl7-listener/requirements.txt \
                --severity high
  waitFor: ['-']

# ──────────────────────────────────────────
# STEP 2: TypeScript/Angular Linting
# ──────────────────────────────────────────
- id: angular-lint
  name: node:22-alpine
  entrypoint: sh
  args:
    - -c
    - |
      cd frontend
      npm ci --prefer-offline --silent
      npm run lint -- --format github-actions
  waitFor: ['-']

# ──────────────────────────────────────────
# STEP 3: Python Unit Tests + Coverage Gate
# ──────────────────────────────────────────
- id: python-unit-tests
  name: python:3.12-slim
  entrypoint: sh
  args:
    - -c
    - |
      apt-get update -q && apt-get install -y -q gcc libpq-dev
      pip install pytest pytest-asyncio pytest-cov --quiet
      # Install all service requirements
      for svc in services/*/; do
        [ -f "$svc/requirements.txt" ] && pip install -r "$svc/requirements.txt" --quiet
      done
      pytest services/ \
        --cov=services \
        --cov-report=xml:coverage.xml \
        --cov-fail-under=80 \
        --tb=short \
        -q
  waitFor: ['python-lint-ruff', 'python-sast-bandit']

# ──────────────────────────────────────────
# STEP 4: Angular Unit Tests
# ──────────────────────────────────────────
- id: angular-unit-tests
  name: node:22-alpine
  entrypoint: sh
  args:
    - -c
    - |
      cd frontend
      npm ci --prefer-offline --silent
      npm run test -- --no-watch --no-progress --browsers=ChromeHeadlessCI \
        --code-coverage \
        --coverage-threshold='{"global":{"statements":80,"lines":80}}'
  waitFor: ['angular-lint']
  env:
    - 'CHROME_BIN=/usr/bin/chromium-browser'

# ──────────────────────────────────────────
# STEP 5a: Docker Build — Python services
# ──────────────────────────────────────────
- id: docker-build-api-gateway
  name: gcr.io/cloud-builders/docker
  args:
    - build
    - --file=docker/python-service/Dockerfile
    - --tag=$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT/api-gateway:git-$_SHORT_SHA
    - --tag=$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT/api-gateway:latest
    - --cache-from=$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT/api-gateway:latest
    - --build-arg=BUILDKIT_INLINE_CACHE=1
    - services/api-gateway
  waitFor: ['python-unit-tests']
  env:
    - 'DOCKER_BUILDKIT=1'

# Repeat pattern for each service (abbreviated — same structure for all 10 services)
# In practice: use a Cloud Build dynamic matrix or a script step to iterate services.yaml

# ──────────────────────────────────────────
# STEP 5b: Docker Build — Angular PWA
# ──────────────────────────────────────────
- id: docker-build-angular-pwa
  name: gcr.io/cloud-builders/docker
  args:
    - build
    - --file=docker/angular-pwa/Dockerfile
    - --tag=$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT/angular-pwa:git-$_SHORT_SHA
    - --tag=$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT/angular-pwa:latest
    - --cache-from=$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT/angular-pwa:latest
    - frontend
  waitFor: ['angular-unit-tests']
  env:
    - 'DOCKER_BUILDKIT=1'

# ──────────────────────────────────────────
# STEP 6: Push images to Artifact Registry
# ──────────────────────────────────────────
- id: push-all-images
  name: gcr.io/cloud-builders/docker
  entrypoint: sh
  args:
    - -c
    - |
      IMAGES="api-gateway hl7-listener coordinator-agent docs-agent medrecon-agent \
              bed-mgmt-agent followup-agent comms-agent ml-inference notification-svc angular-pwa"
      BASE="$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT"
      for img in $IMAGES; do
        docker push "$BASE/$img:git-$_SHORT_SHA"
        docker push "$BASE/$img:latest"
      done
  waitFor:
    - docker-build-api-gateway
    - docker-build-angular-pwa
    # Add all other docker-build-* step IDs here

# Save SHORT_SHA for downstream steps
- id: write-sha
  name: alpine
  entrypoint: sh
  args:
    - -c
    - echo "$_SHORT_SHA" > /workspace/short_sha.txt
  waitFor: ['push-all-images']

artifacts:
  objects:
    location: gs://smarthandoff-tf-state-$_ENVIRONMENT/build-artifacts/$BUILD_ID/
    paths:
      - coverage.xml
      - /workspace/short_sha.txt
```

### 2. Service-Specific Build Script (for all 10 services efficiently)

Rather than 10 identical Cloud Build steps (which hit YAML limits), use a build script:

`.cloudbuild/scripts/build_services.sh`:
```bash
#!/bin/bash
set -euo pipefail

REGISTRY="$1"      # e.g. us-central1-docker.pkg.dev/smarthandoff-staging/smarthandoff-staging
SHORT_SHA="$2"

SERVICES="api-gateway hl7-listener coordinator-agent docs-agent medrecon-agent \
           bed-mgmt-agent followup-agent comms-agent ml-inference notification-svc"

build_service() {
  local SERVICE="$1"
  local SVC_DIR="services/$SERVICE"
  local DOCKERFILE

  # Determine which Dockerfile template to use
  if grep -q "langchain" "$SVC_DIR/requirements.txt" 2>/dev/null; then
    DOCKERFILE="docker/agent-service/Dockerfile"
  else
    DOCKERFILE="docker/python-service/Dockerfile"
  fi

  echo "--- Building $SERVICE (using $DOCKERFILE) ---"
  docker build \
    --file="$DOCKERFILE" \
    --tag="$REGISTRY/$SERVICE:git-$SHORT_SHA" \
    --tag="$REGISTRY/$SERVICE:latest" \
    --cache-from="$REGISTRY/$SERVICE:latest" \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    "$SVC_DIR"

  docker push "$REGISTRY/$SERVICE:git-$SHORT_SHA"
  docker push "$REGISTRY/$SERVICE:latest"
}

# Build all services in parallel (background jobs)
pids=()
for SVC in $SERVICES; do
  build_service "$SVC" &
  pids+=($!)
done

# Wait for all builds and collect exit codes
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || { echo "A service build failed"; failed=1; }
done

exit "$failed"
```

### 3. Cloud Build Trigger for Main Branch (Terraform)

```hcl
# In a new ci_triggers Terraform module or added to cloud_run module
resource "google_cloudbuild_trigger" "main_pipeline" {
  name    = "main-ci-pipeline-${var.environment}"
  project = var.project_id

  github {
    owner = var.github_owner
    name  = var.github_repo
    push  { branch = "^main$" }
  }

  # Trigger only on changes to service code, Dockerfiles, or tests
  included_files = [
    "services/**",
    "frontend/**",
    "docker/**",
    ".cloudbuild/build.yaml",
    ".cloudbuild/scripts/**",
  ]

  filename = ".cloudbuild/build.yaml"

  substitutions = {
    _REGION      = "us-central1"
    _ENVIRONMENT = "staging"
  }

  service_account = "projects/${var.project_id}/serviceAccounts/cloudbuild-sa@${var.project_id}.iam.gserviceaccount.com"
}
```

### 4. Quality Gate Configuration (`pyproject.toml`)

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
select = ["E", "F", "B", "S", "I"]  # pycodestyle, pyflakes, bugbear, bandit-like, isort
ignore = ["S101"]  # Allow assert in tests

[tool.ruff.per-file-ignores]
"*/tests/*" = ["S", "B"]  # Relax security rules in test files

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["services"]
python_files = ["test_*.py", "*_test.py"]

[tool.coverage.run]
source = ["services"]
omit = ["*/tests/*", "*/migrations/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

## Acceptance Criteria

- [ ] Cloud Build trigger `main-ci-pipeline-staging` fires on push to `main` within 2 minutes
- [ ] Pipeline step `python-lint-ruff` fails (exit code ≠ 0) if any Python file has a ruff violation — verified by introducing a deliberate violation in a test branch
- [ ] Pipeline step `python-sast-bandit` fails on a deliberate HIGH severity issue (e.g., `import subprocess` with `shell=True`) — blocks build
- [ ] `python-unit-tests` fails when test coverage drops below 80%: confirmed by deleting test files and re-running
- [ ] Docker build uses `--cache-from` to accelerate subsequent builds; second build of same service completes in <60 seconds (vs. >2 min cold build)
- [ ] `push-all-images` step produces images tagged with both `git-{SHORT_SHA}` and `latest` — confirmed via `gcloud artifacts docker images list` showing both tags
- [ ] All build steps run in correct dependency order: lint → test → build → push (parallel where possible)

## Files to Create

```
.cloudbuild/build.yaml
.cloudbuild/scripts/build_services.sh
pyproject.toml                         (ruff + pytest + coverage config)
frontend/.eslintrc.json                (Angular/TypeScript ESLint config)
frontend/karma.conf.js                 (Karma config with ChromeHeadlessCI)
```

## Notes

- `DOCKER_BUILDKIT=1` enables BuildKit for significantly faster multi-stage builds and better layer caching
- `--cache-from` with `latest` requires that `latest` was previously pushed; first build will be slow (no cache)
- Parallel Docker builds via background shell jobs (`&`) reduce wall-clock time significantly — 10 sequential builds × 3 min = 30 min; parallel = ~5 min
- `E2_HIGHCPU_8` machine type is cost-effective for parallel Docker builds; 8 vCPUs handle concurrent image builds efficiently
