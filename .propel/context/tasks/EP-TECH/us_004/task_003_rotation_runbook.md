---
task_id: task_003
story_id: us_004
epic: EP-TECH
title: Secret Rotation Runbook and Cloud Run Zero-Downtime Rotation Verification
layer: Operations / Security
effort_hours: 1
sequence: 3
status: Draft
---

# TASK-003: Secret Rotation Runbook and Cloud Run Zero-Downtime Rotation Verification

> **Story:** EP-TECH/US-004 | **Layer:** Operations / Security | **Effort:** 1 hour | **Seq:** 3 of 3

## Objective

Document and test the secret rotation procedure that deploys a new secret version without requiring a container rebuild or code deployment — satisfying AC-4. Also verify the SecOps bootstrap procedure (AC-1) for populating all placeholder values on first deployment.

## Implementation Steps

### 1. SecOps Bootstrap Script (`infra/scripts/populate_secrets.sh`)

Run by SecOps after `terraform apply` to replace all placeholder values:

```bash
#!/bin/bash
# infra/scripts/populate_secrets.sh
# Usage: ENV=staging ./infra/scripts/populate_secrets.sh
# Prerequisites: gcloud auth login with secretmanager.secretVersions.add permission

set -euo pipefail

ENV="${ENV:-dev}"
PROJECT="smarthandoff-$ENV"

echo "=== SmartHandoff Secret Bootstrap ==="
echo "Project: $PROJECT | Environment: $ENV"
echo ""
echo "This script will prompt you for each secret value."
echo "Values are sent directly to Secret Manager via gcloud — never stored locally."
echo ""

prompt_and_store() {
  local SECRET_NAME="$1"
  local DESCRIPTION="$2"
  local FULL_NAME="smarthandoff-${SECRET_NAME}-${ENV}"

  echo "── $FULL_NAME ──"
  echo "  Description: $DESCRIPTION"

  # Use read -s to prevent terminal echo of sensitive values
  read -r -s -p "  Enter value (hidden): " SECRET_VALUE
  echo ""  # Newline after hidden input

  if [ -z "$SECRET_VALUE" ]; then
    echo "  SKIPPED (empty value)"
    return
  fi

  echo -n "$SECRET_VALUE" | \
    gcloud secrets versions add "$FULL_NAME" \
      --data-file=- \
      --project="$PROJECT"

  echo "  ✓ Stored"
  echo ""

  # Immediately clear from shell memory
  unset SECRET_VALUE
}

# Database
prompt_and_store "db-password"           "PostgreSQL application user password (from Cloud SQL)"

# PHI Encryption (generate new AES-256 keys if not existing)
echo "Generate new PHI encryption keys? [y/N]"
read -r GEN_KEYS
if [ "$GEN_KEYS" = "y" ]; then
  PHI_KEY=$(python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())")
  PHI_DET_KEY=$(python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())")
  echo -n "$PHI_KEY" | gcloud secrets versions add "smarthandoff-phi-encryption-key-$ENV" --data-file=- --project="$PROJECT"
  echo -n "$PHI_DET_KEY" | gcloud secrets versions add "smarthandoff-phi-encryption-key-det-$ENV" --data-file=- --project="$PROJECT"
  echo "✓ PHI encryption keys generated and stored"
  unset PHI_KEY PHI_DET_KEY
else
  prompt_and_store "phi-encryption-key"     "Base64-encoded AES-256-GCM key for PHI fields"
  prompt_and_store "phi-encryption-key-det" "Base64-encoded deterministic AES-256-GCM key for MRN lookups"
fi

# JWT Keys (generate RSA keypair if not existing)
echo "Generate new JWT RS256 keypair? [y/N]"
read -r GEN_JWT
if [ "$GEN_JWT" = "y" ]; then
  openssl genrsa -out /tmp/jwt_private.pem 4096 2>/dev/null
  openssl rsa -in /tmp/jwt_private.pem -pubout -out /tmp/jwt_public.pem 2>/dev/null
  gcloud secrets versions add "smarthandoff-jwt-signing-key-private-$ENV" \
    --data-file=/tmp/jwt_private.pem --project="$PROJECT"
  gcloud secrets versions add "smarthandoff-jwt-signing-key-public-$ENV" \
    --data-file=/tmp/jwt_public.pem --project="$PROJECT"
  rm /tmp/jwt_private.pem /tmp/jwt_public.pem
  echo "✓ JWT RS256 keypair generated and stored"
else
  prompt_and_store "jwt-signing-key-private" "PEM-encoded RSA private key for JWT signing"
  prompt_and_store "jwt-signing-key-public"  "PEM-encoded RSA public key for JWT verification"
fi

# OIDC, FHIR, Vertex AI, Twilio, SendGrid
prompt_and_store "oidc-client-id"       "Hospital SSO OIDC client ID"
prompt_and_store "oidc-client-secret"   "Hospital SSO OIDC client secret"
prompt_and_store "oidc-discovery-url"   "OIDC discovery URL (e.g. https://accounts.hospital.health/.well-known/openid-configuration)"
prompt_and_store "fhir-base-url"        "FHIR R4 base URL (e.g. https://fhir.hospital.health/api/FHIR/R4)"
prompt_and_store "fhir-client-id"       "SMART on FHIR client ID"
prompt_and_store "fhir-client-secret"   "SMART on FHIR client secret"
prompt_and_store "vertex-ai-project"    "GCP project ID for Vertex AI calls (usually same as main project)"
prompt_and_store "twilio-account-sid"   "Twilio account SID (starts with AC)"
prompt_and_store "twilio-auth-token"    "Twilio auth token"
prompt_and_store "twilio-verify-service-sid" "Twilio Verify service SID (starts with VA)"
prompt_and_store "twilio-phone-number"  "Twilio SMS sender number (E.164 format, e.g. +15005550006)"
prompt_and_store "sendgrid-api-key"     "SendGrid API key (starts with SG.)"

echo ""
echo "=== Bootstrap Complete ==="
echo "All secrets stored in Secret Manager for project: $PROJECT"
echo ""
echo "Next steps:"
echo "  1. Deploy a test Cloud Run revision to verify bindings work"
echo "  2. Run: gcloud run services update api-gateway-$ENV --region=us-central1 --project=$PROJECT"
echo "  3. Check service logs for 'Settings loaded successfully'"
```

### 2. Secret Rotation Procedure (`infra/ROTATION.md`)

```markdown
# Secret Rotation Procedure

## When to Rotate

| Secret | Rotation Trigger | Frequency |
|--------|-----------------|-----------|
| DB password | Security incident, staff change | Quarterly + on incident |
| PHI encryption key | Security incident only | NEVER rotate without migration plan |
| JWT signing key | Security incident, algorithm upgrade | Annually |
| OIDC client secret | SSO provider requires rotation | Per provider policy |
| FHIR client secret | EHR vendor requires rotation | Per vendor policy |
| Twilio auth token | Security incident | On incident |
| SendGrid API key | Security incident | On incident |

## Rotation Steps (Zero-Downtime)

### Step 1 — Add new secret version (do NOT delete old version yet)

```bash
echo -n "new-secret-value" | \
  gcloud secrets versions add smarthandoff-{secret-name}-{env} \
    --data-file=- \
    --project=smarthandoff-{env}
```

### Step 2 — Verify new version is ENABLED

```bash
gcloud secrets versions list smarthandoff-{secret-name}-{env} --project=smarthandoff-{env}
# Should show both version 1 (ENABLED) and version 2 (ENABLED)
```

### Step 3 — Deploy a new Cloud Run revision to pick up the new version

Cloud Run services using `version: "latest"` pick up the new secret on the next revision. Force a new revision:

```bash
gcloud run services update {service-name}-{env} \
  --region=us-central1 \
  --project=smarthandoff-{env} \
  --set-env-vars=ROTATION_TIMESTAMP=$(date +%s)  # Force a new revision
```

### Step 4 — Verify new revision is healthy

```bash
gcloud run services describe {service-name}-{env} \
  --region=us-central1 \
  --format=json | jq '.status.conditions[] | select(.type=="Ready")'
# Must show "status": "True"
```

Check logs for successful startup:
```bash
gcloud run services logs read {service-name}-{env} \
  --region=us-central1 \
  --limit=20 | grep "Settings loaded"
```

### Step 5 — Disable (NOT delete) old secret version

After verifying the new revision is healthy with the new secret:

```bash
gcloud secrets versions disable 1 \
  --secret=smarthandoff-{secret-name}-{env} \
  --project=smarthandoff-{env}
```

### Step 6 — Delete old version (after 24-hour observation period)

```bash
gcloud secrets versions destroy 1 \
  --secret=smarthandoff-{secret-name}-{env} \
  --project=smarthandoff-{env}
```
```

### 3. Terraform: Cloud Run Secret Binding Verification Test

Add to the Terraform module outputs for operational verification:

```hcl
# modules/cloud_run/outputs.tf — add test helper
output "secret_binding_verification_commands" {
  value = {
    for svc in local.services : svc => join(" ", [
      "gcloud run services describe ${svc}-${var.environment}",
      "--region=${var.region}",
      "--format='json'",
      "| jq '.spec.template.spec.containers[0].env[]",
      "| select(.valueFrom.secretKeyRef != null)",
      "| .name'"
    ])
  }
  description = "Run these commands to verify Secret Manager bindings are configured on each service"
}
```

### 4. Acceptance Test Script (`infra/scripts/verify_secret_bindings.sh`)

```bash
#!/bin/bash
# Verify all expected env vars are bound via secretKeyRef on each service

set -euo pipefail

ENV="${ENV:-dev}"
PROJECT="smarthandoff-$ENV"
REGION="us-central1"

EXPECTED_BINDINGS=(
  "api-gateway:DB_PASSWORD"
  "api-gateway:PHI_ENCRYPTION_KEY"
  "api-gateway:JWT_SIGNING_KEY_PRIVATE"
  "api-gateway:OIDC_CLIENT_SECRET"
  "docs-agent:FHIR_CLIENT_SECRET"
  "docs-agent:VERTEX_AI_PROJECT"
  "notification-svc:TWILIO_AUTH_TOKEN"
  "notification-svc:SENDGRID_API_KEY"
)

FAILED=0
for BINDING in "${EXPECTED_BINDINGS[@]}"; do
  SERVICE="${BINDING%%:*}"
  ENV_VAR="${BINDING##*:}"
  FULL_SERVICE="${SERVICE}-${ENV}"

  RESULT=$(gcloud run services describe "$FULL_SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format='json' 2>/dev/null | \
    jq -r --arg VAR "$ENV_VAR" \
      '.spec.template.spec.containers[0].env[]? | select(.name == $VAR) | .valueFrom.secretKeyRef.name // empty')

  if [ -n "$RESULT" ]; then
    echo "✓ $FULL_SERVICE: $ENV_VAR → secretKeyRef: $RESULT"
  else
    echo "✗ MISSING: $FULL_SERVICE: $ENV_VAR has no secretKeyRef binding"
    FAILED=1
  fi
done

exit "$FAILED"
```

## Acceptance Criteria

- [ ] **AC-1:** `./infra/scripts/populate_secrets.sh` runs successfully in dev environment; all 21 secrets have version 1 with status ENABLED and non-placeholder values — confirmed via `gcloud secrets versions list` for each secret
- [ ] **AC-4:** Rotation test: update `smarthandoff-db-password-dev` to a new value → force new Cloud Run revision → verify service starts successfully with new password → confirm old revision still serves traffic during transition (zero downtime)
- [ ] **AC-4:** `gcloud run services describe api-gateway-dev --format=json | jq '.spec.template.spec.containers[0].env[] | select(.valueFrom.secretKeyRef) | .name'` lists all expected secret-bound env vars
- [ ] **AC-5:** `./infra/scripts/verify_secret_bindings.sh` exits 0 — all expected bindings confirmed on all services
- [ ] `ROTATION.md` accessible in `infra/ROTATION.md`; reviewed and approved by SecOps lead
- [ ] Bootstrap script tested: run with `ENV=dev` in a fresh Cloud Shell session — all secrets stored without values appearing in terminal history (use `read -s`) or shell history (`history` shows only the command, not the value)

## Files to Create

```
infra/scripts/populate_secrets.sh
infra/scripts/verify_secret_bindings.sh
infra/ROTATION.md
```

## Notes

- `read -s` in bash suppresses terminal echo but the value may still appear in bash history — append ` ; history -d $((HISTCMD-1))` after each `read` call to also clear from history, or run with `HISTFILE=/dev/null` prefixed
- **PHI encryption key rotation requires a data migration plan** — all encrypted PHI columns must be re-encrypted with the new key before the old key is disabled; this is a separate (complex) operational procedure documented in `infra/PHI_KEY_MIGRATION.md`
- Secret Manager `version: "latest"` binding is used for all Cloud Run services; this means a new secret version is picked up on the NEXT revision deployment, not immediately — the rotation step 3 (force new revision) is required to activate the new secret value
- `destroy` (step 6) is irreversible — always observe for 24 hours after disabling the old version before destroying
