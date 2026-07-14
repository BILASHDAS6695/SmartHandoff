---
id: TASK-007
title: "Document Secret Rotation Procedure in `infra/BOOTSTRAP.md`"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: Documentation
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: Security Engineer
upstream: [TASK-001]
---

# TASK-007: Document Secret Rotation Procedure in `infra/BOOTSTRAP.md`

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Documentation | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-005 DoD requires: *"Secret rotation procedure documented in `infra/BOOTSTRAP.md`"*. Manual rotation (without Cloud Functions trigger) is acceptable for Sprint 1. The rotation procedure must demonstrate Scenario 3 compliance: Cloud Run picks up the new secret within 60 seconds of the next request without a manual redeployment, because Cloud Run resolves `version = "latest"` on each new instance start.

`infra/BOOTSTRAP.md` already has Step 3 (Populate Secret Values) from the initial bootstrapping setup. This task adds a dedicated **"Secret Rotation"** section covering the step-by-step manual procedure, the verification steps, and the rollback procedure in case the new secret value is invalid.

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **Scenario 3** | Secret rotation does not require redeployment — documented as the standard procedure |
| **DoD** | Secret rotation procedure documented in `infra/BOOTSTRAP.md` |

---

## Implementation Steps

### 1. Append a "Secret Rotation" section to `infra/BOOTSTRAP.md`

Add the following section after the existing "Destroying an Environment" section:

````markdown
---

## Secret Rotation Procedure

Secrets are stored in GCP Secret Manager and mounted in Cloud Run services as
environment variables using `version = "latest"`. This means **no redeployment is
required** — Cloud Run resolves the latest enabled version on each new instance start.
Running instances pick up the new value within 60 seconds of the next request.

### When to Rotate

| Secret | Trigger |
|--------|---------|
| `db_password` | Every 90 days or immediately after any suspected exposure |
| `jwt_signing_key_private` | Every 180 days or immediately after any suspected exposure |
| `fhir_client_secret` | When notified by EHR vendor or every 90 days |
| `twilio_auth_token` | When notified by Twilio or every 90 days |
| `sendgrid_api_key` | When notified by SendGrid or every 90 days |
| `oidc_client_secret` | When notified by Hospital SSO team |
| All secrets | Immediately on any suspected breach or unauthorized access |

### Rotation Steps

**Step 1 — Add the new secret version (do NOT disable the old version yet)**

```bash
# Replace SECRET_NAME and ENV with actual values (e.g., smarthandoff-db-password-prod)
NEW_VALUE="your-new-secret-value"
SECRET_NAME="smarthandoff-{secret-name}-{env}"
PROJECT="smarthandoff-{env}"

echo -n "${NEW_VALUE}" | \
  gcloud secrets versions add "${SECRET_NAME}" \
    --data-file=- \
    --project="${PROJECT}"
```

**Step 2 — Verify the new version is ENABLED**

```bash
gcloud secrets versions list "${SECRET_NAME}" \
  --project="${PROJECT}" \
  --format="table(name,state,createTime)"
# Latest version should show state=ENABLED
```

**Step 3 — Test the new credential out-of-band**

Before disabling the old version, verify the new credential works:

- For `db_password`: connect to Cloud SQL using the new password from Cloud Shell.
- For API keys (Twilio, SendGrid, etc.): make a test API call using the new key.
- For `jwt_signing_key_private`: verify token signing/verification with the new key pair.

**Step 4 — Disable the old secret version**

```bash
# List versions to find the old version number (N-1)
OLD_VERSION=$(gcloud secrets versions list "${SECRET_NAME}" \
  --project="${PROJECT}" \
  --format="value(name)" \
  --sort-by="~createTime" \
  --filter="state=ENABLED" \
  | tail -1)

gcloud secrets versions disable "${OLD_VERSION}" \
  --secret="${SECRET_NAME}" \
  --project="${PROJECT}"
```

**Step 5 — Verify Cloud Run picks up the new version**

Cloud Run resolves `version = "latest"` on each new instance start.
Force a new instance by sending a request to the relevant service:

```bash
# Example: verify coordinator-agent picked up new db_password
curl -s -o /dev/null -w "%{http_code}" \
  https://coordinator-agent-{env}-{hash}-uc.a.run.app/health
# Expected: 200 (service started, resolved new db_password on startup)
```

For latency-sensitive services (`cpu_idle = false`, i.e., `api-gateway`, `hl7-listener`,
`coordinator-agent`), a new instance is started within seconds of the old one being
replaced by Cloud Run's internal scheduling. For `cpu_idle = true` agents, the new
value is picked up at the next instance cold-start.

**Step 6 — Confirm no services are using the old version**

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND textPayload:"Secret Manager"' \
  --project="${PROJECT}" --limit=20 --format="table(timestamp,textPayload)"
# Inspect for any errors related to the disabled secret version
```

### Rollback Procedure

If the new credential is invalid and services start failing:

```bash
# Re-enable the old version immediately
gcloud secrets versions enable "${OLD_VERSION}" \
  --secret="${SECRET_NAME}" \
  --project="${PROJECT}"

# Disable the bad new version
gcloud secrets versions disable "${NEW_VERSION}" \
  --secret="${SECRET_NAME}" \
  --project="${PROJECT}"
```

Cloud Run picks up the re-enabled old version within 60 seconds on the next instance start.

### Developer Pre-Commit Hook Setup

All contributors must install the `gitleaks` pre-commit hook to prevent accidental
secret commits:

```bash
pip install pre-commit
pre-commit install
```

To scan the entire repository manually:

```bash
pre-commit run --all-files
```
````

---

## Files Modified / Created

| File | Action |
|---|---|
| `infra/BOOTSTRAP.md` | Append "Secret Rotation Procedure" section |

---

## Verification

```bash
# Review the rendered Markdown
cat infra/BOOTSTRAP.md | grep -A 5 "Secret Rotation"
# Expected: Section header and rotation steps present

# Confirm all secrets listed in TASK-001 are represented in the rotation table
```
