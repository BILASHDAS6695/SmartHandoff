---
id: TASK-008
title: "End-to-End Secret Management Validation and DoD Signoff"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: Validation
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: Security Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007]
---

# TASK-008: End-to-End Secret Management Validation and DoD Signoff

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

With all IaC (TASK-001 through TASK-004), developer tooling (TASK-005), CI/CD scanning (TASK-006), and documentation (TASK-007) implemented, this task validates every Acceptance Criterion and Definition of Done item before marking US-005 complete. Validation is performed against the `dev` environment after a full `terraform apply` that includes the `secrets` module.

---

## Acceptance Criteria Validated

| Scenario | Requirement | Validation Method |
|---|---|---|
| **Scenario 1** | All required secrets exist with ≥1 ENABLED version | `gcloud secrets list` + `gcloud secrets versions list` |
| **Scenario 2** | Zero secrets in production container image layers | `trufflehog` scan of Artifact Registry image |
| **Scenario 3** | Secret rotation without redeployment — new value active within 60 s | Rotate `db_password`; observe Cloud Run picks up new value |
| **Scenario 4** | Pre-commit hook blocks secret commits | Attempt commit with a fake AWS access key |

---

## Validation Steps

### Step 1: Terraform Apply — `dev` Environment (TASK-001 through TASK-004)

```bash
cd infra/terraform/environments/dev
terraform init
terraform validate
# Expected: Success! The configuration is valid.

terraform plan -out=tfplan
terraform apply tfplan
```

Expected plan output includes:
```
module.secrets.google_secret_manager_secret.secrets["db_password"]       will be created
module.secrets.google_secret_manager_secret.secrets["fhir_client_secret"] will be created
# ... (19 secrets total)
module.secrets.google_secret_manager_secret_iam_member.service_access["api-gateway__jwt_signing_key_private"] will be created
# ... (N IAM bindings)
```

### Step 2: Validate Scenario 1 — All Required Secrets Exist

```bash
PROJECT="smarthandoff-dev"

# Confirm all 19 secrets are present
gcloud secrets list --project="${PROJECT}" --format="table(name,createTime)"
# Expected: 19 rows

# Spot-check that each has at least 1 ENABLED version
for secret in db-password fhir-client-secret twilio-auth-token sendgrid-api-key \
              jwt-signing-key-private oidc-client-secret gcs-hmac-key; do
  STATE=$(gcloud secrets versions list "smarthandoff-${secret}-dev" \
    --project="${PROJECT}" --format="value(state)" | head -1)
  echo "smarthandoff-${secret}-dev: ${STATE}"
done
# Expected: all show ENABLED
```

### Step 3: Validate Scenario 2 — No Secrets in Container Images

```bash
# Pull and scan the api-gateway image from Artifact Registry
IMAGE="us-central1-docker.pkg.dev/${PROJECT}/smarthandoff/api-gateway:latest"

trufflehog docker \
  --image="${IMAGE}" \
  --only-verified \
  --fail

# Expected: exit code 0 — no verified secrets found
# If exit code 1: review trufflehog output and remediate before signing off
```

### Step 4: Validate Scenario 3 — Secret Rotation Without Redeployment

```bash
PROJECT="smarthandoff-dev"
SECRET="smarthandoff-db-password-dev"

# Record the current Cloud Run instance count before rotation
BEFORE=$(gcloud run services describe coordinator-agent-dev \
  --region=us-central1 --project="${PROJECT}" \
  --format="value(status.observedGeneration)")

# Add a new secret version (use a fake value for dev validation)
echo -n "rotated-dev-password-$(date +%s)" | \
  gcloud secrets versions add "${SECRET}" \
    --data-file=- --project="${PROJECT}"

# Disable the previous version
PREV=$(gcloud secrets versions list "${SECRET}" \
  --project="${PROJECT}" --format="value(name)" \
  --sort-by="~createTime" --filter="state=ENABLED" | sed -n '2p')
gcloud secrets versions disable "${PREV}" \
  --secret="${SECRET}" --project="${PROJECT}"

# Send a request to coordinator-agent to force instance start
sleep 5
curl -s -o /dev/null -w "%{http_code}" \
  "$(gcloud run services describe coordinator-agent-dev \
     --region=us-central1 --project="${PROJECT}" \
     --format='value(status.url)')/health"
# Expected: 200 (new instance started with new secret version)

# Confirm no new revision was deployed
AFTER=$(gcloud run services describe coordinator-agent-dev \
  --region=us-central1 --project="${PROJECT}" \
  --format="value(status.observedGeneration)")
echo "Generation before: ${BEFORE} — after: ${AFTER}"
# Expected: identical — no redeployment occurred
```

### Step 5: Validate Scenario 4 — Pre-Commit Hook Blocks Secret Commits

```bash
# Install hooks on dev machine (if not already done)
pip install pre-commit
pre-commit install

# Attempt to stage and commit a fake AWS access key
echo 'AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE' > /tmp/test_leak.env
cp /tmp/test_leak.env services/api-gateway/test_leak.env
git add services/api-gateway/test_leak.env
git commit -m "test: should be blocked"
# Expected: gitleaks hook FAILED
# Message: "services/api-gateway/test_leak.env: aws-access-token detected"

# Clean up
git restore --staged services/api-gateway/test_leak.env
rm services/api-gateway/test_leak.env
```

### Step 6: Validate No Project-Level secretAccessor Binding Exists

```bash
gcloud projects get-iam-policy smarthandoff-dev \
  --format=json \
  | jq '.bindings[] | select(.role == "roles/secretmanager.secretAccessor")'
# Expected: no output — binding is at individual secret resource level only
```

---

## Definition of Done Checklist

| DoD Item | Status |
|---|---|
| All Secret Manager secrets declared in `secrets` module with placeholder values | ☐ |
| Cloud Run services use `secretenv` to access secrets at runtime | ☐ |
| `gitleaks` pre-commit hook in `.pre-commit-config.yaml` | ☐ |
| Secret scanning step added to CI/CD pipeline (source + image) | ☐ |
| IAM: each Cloud Run SA has `secretAccessor` only on its own secrets | ☐ |
| Secret rotation procedure documented in `infra/BOOTSTRAP.md` | ☐ |
| Code reviewed and approved by Security Engineer | ☐ |

Sign off by updating `US-005.md` status from `Draft` to `Done` once all checklist items are confirmed.
