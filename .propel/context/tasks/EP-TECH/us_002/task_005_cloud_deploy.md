---
task_id: task_005
story_id: us_002
epic: EP-TECH
title: Cloud Deploy — Delivery Pipelines, Canary Targets, and Prod Approval Gate
layer: Continuous Delivery
effort_hours: 2
sequence: 5
status: Draft
---

# TASK-005: Cloud Deploy — Delivery Pipelines, Canary Targets, and Prod Approval Gate

> **Story:** EP-TECH/US-002 | **Layer:** Continuous Delivery | **Effort:** 2 hours | **Seq:** 5 of 7

## Objective

Configure Google Cloud Deploy delivery pipelines for all 10 Cloud Run services. Each pipeline has two targets: `staging` (auto-deploy, 10% canary → 100%) and `prod` (requires manual approval gate). The canary traffic split is enforced by Cloud Run traffic management, not load balancer weights.

## Implementation Steps

### 1. Cloud Deploy Pipeline for API Gateway (representative — repeat pattern for all services)

`.cloudbuild/deploy/api-gateway-pipeline.yaml`:

```yaml
apiVersion: deploy.cloud.google.com/v1
kind: DeliveryPipeline
metadata:
  name: api-gateway-pipeline
  annotations:
    description: "API Gateway delivery pipeline — canary → full → prod gate"
spec:
  serialPipeline:
    stages:
      # Stage 1: Staging — automated canary then full rollout
      - targetId: staging
        profiles: []
        strategy:
          canary:
            runtimeConfig:
              cloudRun:
                automaticTrafficControl: true
            canaryDeployment:
              percentages: [10]  # 10% canary traffic first
              verify: true       # Require verification (Task 006) before promoting

      # Stage 2: Production — requires human approval
      - targetId: prod
        profiles: []
        strategy:
          standard:
            verify: false  # No automated verify in prod — human reviewed staging already
---
apiVersion: deploy.cloud.google.com/v1
kind: Target
metadata:
  name: staging
spec:
  requireApproval: false  # Auto-deploy to staging
  run:
    location: projects/${_PROJECT_ID}/locations/us-central1
---
apiVersion: deploy.cloud.google.com/v1
kind: Target
metadata:
  name: prod
spec:
  requireApproval: true   # Manual approval gate for production (AC-5)
  run:
    location: projects/smarthandoff-prod/locations/us-central1
```

### 2. Cloud Run Skaffold Config (required by Cloud Deploy)

`.cloudbuild/deploy/skaffold.yaml`:

```yaml
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: smarthandoff

deploy:
  cloudrun: {}  # Use Cloud Run deployer

profiles:
  - name: staging
    deploy:
      cloudrun:
        projectid: smarthandoff-staging
        region: us-central1

  - name: prod
    deploy:
      cloudrun:
        projectid: smarthandoff-prod
        region: us-central1
```

### 3. Cloud Run Service Manifest for Deployment (`manifests/api-gateway.yaml`)

Cloud Deploy needs a Cloud Run service YAML that it can update on each release:

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: api-gateway-staging
  labels:
    managed-by: cloud-deploy
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "2"
        autoscaling.knative.dev/maxScale: "20"
        run.googleapis.com/vpc-access-connector: projects/smarthandoff-staging/locations/us-central1/connectors/smarthandoff-connector-staging
        run.googleapis.com/vpc-access-egress: all-traffic
    spec:
      containerConcurrency: 100
      containers:
        - image: IMAGE_PLACEHOLDER  # Replaced by Cloud Deploy on each release
          resources:
            limits:
              cpu: "2000m"
              memory: 2Gi
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /health
            periodSeconds: 10
          startupProbe:
            httpGet:
              path: /ready
            periodSeconds: 5
            failureThreshold: 12
```

### 4. Cloud Build Step — Create Release in Cloud Deploy

Add this step to `.cloudbuild/build.yaml` after the vulnerability scan gate passes:

```yaml
# ──────────────────────────────────────────
# STEP 8: Create Cloud Deploy Release (triggers canary deploy to staging)
# ──────────────────────────────────────────
- id: create-cloud-deploy-release
  name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
  entrypoint: bash
  args:
    - -c
    - |
      set -euo pipefail

      REGISTRY="$_REGISTRY/$_PROJECT_ID/smarthandoff-$_ENVIRONMENT"
      SHA="$_SHORT_SHA"

      # Build image substitutions for all services
      IMAGE_SUBS=""
      SERVICES="api-gateway hl7-listener coordinator-agent docs-agent medrecon-agent \
                bed-mgmt-agent followup-agent comms-agent ml-inference notification-svc angular-pwa"
      for SVC in $SERVICES; do
        IMAGE_SUBS="${IMAGE_SUBS}${SVC}=$REGISTRY/$SVC:git-$SHA,"
      done
      IMAGE_SUBS="${IMAGE_SUBS%,}"  # Remove trailing comma

      # Create a release for each service pipeline
      for SVC in $SERVICES; do
        PIPELINE="${SVC}-pipeline"
        echo "Creating release for pipeline: $PIPELINE"

        gcloud deploy releases create "release-$SHA-$(date +%s)" \
          --project="$_PROJECT_ID" \
          --region="$_REGION" \
          --delivery-pipeline="$PIPELINE" \
          --images="$SVC=$REGISTRY/$SVC:git-$SHA" \
          --skaffold-file=".cloudbuild/deploy/skaffold.yaml" \
          --source=".cloudbuild/deploy/" \
          --annotations="git-commit=$SHA,build-id=$BUILD_ID" \
          --async  # Don't wait for deployment — canary verification handles monitoring
      done
  waitFor: ['vulnerability-scan-gate']
```

### 5. Terraform — Cloud Deploy Resources

```hcl
# modules/cloud_deploy/main.tf

locals {
  services = [
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "bed-mgmt-agent", "followup-agent", "comms-agent",
    "ml-inference", "notification-svc"
  ]
}

resource "google_clouddeploy_target" "staging" {
  name     = "staging"
  location = var.region
  project  = var.project_id

  require_approval = false

  run {
    location = "projects/${var.staging_project_id}/locations/${var.region}"
  }
}

resource "google_clouddeploy_target" "prod" {
  name     = "prod"
  location = var.region
  project  = var.project_id

  require_approval = true  # AC-5: manual approval gate

  run {
    location = "projects/${var.prod_project_id}/locations/${var.region}"
  }
}

resource "google_clouddeploy_delivery_pipeline" "service_pipelines" {
  for_each = toset(local.services)

  name     = "${each.value}-pipeline"
  location = var.region
  project  = var.project_id

  serial_pipeline {
    stages {
      target_id = google_clouddeploy_target.staging.name
      strategy {
        canary {
          runtime_config {
            cloud_run { automatic_traffic_control = true }
          }
          canary_deployment {
            percentages = [10]
            verify      = true
          }
        }
      }
    }

    stages {
      target_id = google_clouddeploy_target.prod.name
      strategy {
        standard { verify = false }
      }
    }
  }
}
```

### 6. Cloud Deploy IAM

```hcl
# Cloud Deploy service account can deploy to Cloud Run
resource "google_project_iam_member" "clouddeploy_runner" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "clouddeploy_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}
```

## Acceptance Criteria

- [ ] **AC-5 satisfied:** `gcloud deploy delivery-pipelines list --project={PROJECT} --region=us-central1` shows all 10 service pipelines with two stages: staging (no approval) → prod (requires approval)
- [ ] After a successful push to `main` and passing vulnerability scan: Cloud Deploy release created automatically; Cloud Run staging service shows `10%` traffic on new revision and `90%` on current revision
- [ ] `gcloud deploy targets describe prod --project={PROJECT} --region=us-central1 --format=json | jq '.requireApproval'` returns `true`
- [ ] Manual approval test: create a prod rollout from staging release → verify it stays in `PENDING_APPROVAL` state until approved via `gcloud deploy rollouts approve`
- [ ] Cloud Deploy release annotations include `git-commit` and `build-id` — traceable back to the exact Cloud Build run

## Files to Create

```
.cloudbuild/deploy/api-gateway-pipeline.yaml  (and one per service)
.cloudbuild/deploy/skaffold.yaml
manifests/api-gateway.yaml                    (and one per service)
infra/terraform/modules/cloud_deploy/main.tf
infra/terraform/modules/cloud_deploy/variables.tf
infra/terraform/modules/cloud_deploy/outputs.tf
```

## Notes

- Cloud Deploy's canary for Cloud Run uses **traffic splitting on Cloud Run revisions** — not load balancer weights. `automaticTrafficControl: true` means Cloud Deploy manages the traffic split automatically
- The 10% canary traffic split means real production traffic tests the new revision; metrics collected during this phase feed the rollback decision (Task 006)
- `--async` flag on `gcloud deploy releases create` is intentional — Cloud Build pipeline completes successfully once the release is created; canary observation happens independently via Cloud Monitoring (Task 006)
- Prod deployment requires manual approval via Cloud Console → Cloud Deploy or `gcloud deploy rollouts approve` — this is the governance gate preventing unreviewed code reaching production
