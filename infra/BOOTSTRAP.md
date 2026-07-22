# SmartHandoff Infrastructure — Bootstrap Guide

This document covers the **one-time manual steps** required before
`terraform apply` can run. These steps cannot be automated by Terraform
itself because they create the prerequisites that Terraform depends on.

---

## Prerequisites

| Requirement | Owner | Status |
|-------------|-------|--------|
| GCP projects created (dev / staging / prod) | GCP Admin | ☐ |
| Billing accounts linked to each project | GCP Admin | ☐ |
| GCP Org policies reviewed | GCP Admin | ☐ |
| Terraform state buckets created (Step 1 below) | DevOps | ☐ |
| Secret placeholder values populated (Step 3 below) | SecOps | ☐ |
| Cloud Build GitHub connection configured | DevOps | ☐ |

---

## Step 1 — Create Terraform State Buckets

Run once per environment. Requires `storage.buckets.create` permission.

```bash
for ENV in dev staging prod; do
  PROJECT="smarthandoff-${ENV}"

  gcloud storage buckets create "gs://smarthandoff-tf-state-${ENV}" \
    --project="${PROJECT}" \
    --location=us-central1 \
    --uniform-bucket-level-access

  # Enable versioning so state history is retained
  gcloud storage buckets update "gs://smarthandoff-tf-state-${ENV}" \
    --versioning

  echo "✓ State bucket created: gs://smarthandoff-tf-state-${ENV}"
done
```

Verify:
```bash
gcloud storage buckets describe gs://smarthandoff-tf-state-dev \
  --format="json" | jq '.versioning'
# Expected: {"enabled": true}
```

---

## Step 2 — First terraform apply

```bash
# 1. Authenticate
gcloud auth application-default login

# 2. Set up dev environment
cd infra/terraform/environments/dev
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with real values (NOT committed to git)

# 3. Initialise backend
terraform init -backend-config="bucket=smarthandoff-tf-state-dev"

# 4. Validate configuration
terraform validate
# Expected: Success! The configuration is valid.

# 5. Plan — review all resources
terraform plan -out=tfplan.dev

# 6. Apply
terraform apply tfplan.dev
```

---

## Step 3 — Populate Secret Values

After `terraform apply`, all secrets contain placeholder values.
SecOps must replace them before any service can start:

```bash
# Replace placeholders for each secret
echo -n "actual-value" | \
  gcloud secrets versions add smarthandoff-{secret-name}-{env} \
    --data-file=- \
    --project=smarthandoff-{env}
```

Use the interactive bootstrap script for guided input:
```bash
ENV=dev ./infra/scripts/populate_secrets.sh
```

Secrets to populate (in order):
1. `smarthandoff-db-password-{env}` — from Cloud SQL output
2. `smarthandoff-phi-encryption-key-{env}` — generate: `python3 -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`
3. `smarthandoff-phi-encryption-key-det-{env}` — generate separately
4. `smarthandoff-jwt-signing-key-private-{env}` — `openssl genrsa 4096`
5. `smarthandoff-jwt-signing-key-public-{env}` — from private key
6. `smarthandoff-oidc-client-id-{env}` — from Hospital SSO
7. `smarthandoff-oidc-client-secret-{env}` — from Hospital SSO
8. `smarthandoff-oidc-discovery-url-{env}` — from Hospital SSO
9. `smarthandoff-fhir-base-url-{env}` — from EHR Vendor
10. `smarthandoff-fhir-client-id-{env}` — from EHR Vendor
11. `smarthandoff-fhir-client-secret-{env}` — from EHR Vendor
12. `smarthandoff-vertex-ai-project-{env}` — GCP project ID
13. `smarthandoff-twilio-account-sid-{env}` — from Twilio Console
14. `smarthandoff-twilio-auth-token-{env}` — from Twilio Console
15. `smarthandoff-twilio-verify-service-sid-{env}` — from Twilio Console
16. `smarthandoff-twilio-phone-number-{env}` — from Twilio Console
17. `smarthandoff-sendgrid-api-key-{env}` — from SendGrid Console
18. `smarthandoff-slack-webhook-url-{env}` — from Slack App settings
19. `smarthandoff-gcs-hmac-key-{env}` — GCS HMAC key for portal-bff / docs-agent bucket access

---

## Step 4 — Verify Email Notification Channel

Cloud Monitoring email channels start in `UNVERIFIED` state. After
`terraform apply`, check your oncall inbox for a verification email
from Google and click the confirmation link.

```bash
gcloud monitoring channels describe $(terraform output -raw email_oncall_channel_id) \
  --format="json" | jq '.verificationStatus'
# Must be "VERIFIED" before alerts can be delivered
```

---

## Destroying an Environment (dev/staging only — NEVER prod)

```bash
cd infra/terraform/environments/dev
terraform destroy -auto-approve
```

**Prod has `deletion_protection = true`** on Cloud SQL.
Remove that attribute in a separate plan before attempting destroy.

---

## Adding a New Environment

1. Copy `environments/dev/` to `environments/{new-env}/`
2. Update `backend.tf` bucket name
3. Update `terraform.tfvars.example` with environment-specific values
4. Create state bucket (Step 1 above)
5. Run `terraform init` and `terraform apply`

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
| `phi_encryption_key` | On any suspected breach — requires coordinated key migration |
| All secrets | Immediately on any suspected breach or unauthorized access |

### Rotation Steps

**Step 1 — Add the new secret version (do NOT disable the old version yet)**

```bash
# Replace SECRET_NAME and ENV with actual values
# e.g., SECRET_NAME=smarthandoff-db-password-prod, ENV=prod
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
# Find the previous ENABLED version (second in the sorted list)
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
# Expected: 200
```

For latency-sensitive services (`cpu_idle = false`): `api-gateway`, `hl7-listener`,
`coordinator-agent` — a new instance starts within seconds of Cloud Run's scheduler
cycling old instances. For `cpu_idle = true` agents, the new value is picked up on
the next cold-start.

**Step 6 — Confirm no errors related to the old version**

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" severity>=WARNING' \
  --project="${PROJECT}" --limit=20 \
  --format="table(timestamp,textPayload)"
# Check for any Secret Manager access errors
```

### Rollback Procedure

If the new credential is invalid and services start failing:

```bash
# Re-enable the previous version immediately
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
secret commits. See the repository `README.md` "Pre-Commit Hooks" section for instructions:

```bash
pip install pre-commit
pre-commit install
```

---

## PHI Encryption Key Rotation

SmartHandoff uses AES-256-GCM field-level encryption for all PHI columns
(`patient`, `document`, `chatbot_transcript`). When the encryption key must
be rotated (annual rotation, suspected compromise), follow this procedure.

> **US-007 requirement:** The re-encryption script (`backend/scripts/reencrypt_phi.py`)
> must be executed after each key rotation to migrate all existing PHI records
> from the old key to the new key.

### Prerequisites

- GCP role `roles/secretmanager.secretVersionManager` on the `phi-encryption-key` secret
- Cloud SQL IAM role `roles/cloudsql.client` (for Cloud SQL Auth Proxy access)
- `DATABASE_URL` pointing to the Cloud SQL instance

### Step 1 — Generate a new AES-256 key

```bash
NEW_KEY=$(python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
# IMPORTANT: Store this value securely (e.g., a local password manager).
# Do NOT print or log it in a shared terminal session.
```

### Step 2 — Store the new key as a new Secret Manager version

```bash
PROJECT="smarthandoff-prod"   # or smarthandoff-dev / smarthandoff-staging
echo -n "$NEW_KEY" | \
  gcloud secrets versions add phi-encryption-key \
    --data-file=- \
    --project="$PROJECT"
```

This creates a new version. The previous version remains accessible until
explicitly disabled — do NOT disable it before the re-encryption script completes.

### Step 3 — Retrieve the old key version number

```bash
# List all enabled versions — the second entry is the old version
gcloud secrets versions list phi-encryption-key \
  --project="$PROJECT" \
  --format="table(name,state,createTime)" \
  --filter="state=ENABLED"
# Note the old version number (e.g., "3")
```

### Step 4 — Retrieve the old key value

```bash
OLD_KEY=$(gcloud secrets versions access <old-version-number> \
  --secret=phi-encryption-key \
  --project="$PROJECT")
```

### Step 5 — Run the re-encryption script (dry-run first)

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://<user>:<pass>@localhost/smarthandoff"
export PHI_ENCRYPTION_KEY_OLD="$OLD_KEY"
export PHI_ENCRYPTION_KEY_SECRET_ID="phi-encryption-key"  # Uses new latest version

# Dry run — no DB writes, logs row counts per table
python -m scripts.reencrypt_phi --dry-run --batch-size 100

# If the counts look correct, run for real
python -m scripts.reencrypt_phi --batch-size 100

# To process a single table (e.g., patient only)
python -m scripts.reencrypt_phi --table patient --batch-size 100
```

The script is **idempotent** — if it fails mid-way, re-run it from the
beginning. Already re-encrypted rows will fail decryption with the old key
and must be skipped manually (see Rollback below if this happens).

### Step 6 — Verify ORM decryption works with the new key

```bash
# Spot-check: load a patient record through the API and verify PHI is readable
curl -H "Authorization: Bearer <valid-token>" \
  https://api-gateway-prod.run.app/v1/patients/<patient-id> | jq .
# first_name, last_name, date_of_birth must return plaintext (not ciphertext)
```

### Step 7 — Deploy updated Cloud Run services

After re-encryption completes, all Cloud Run services will automatically pick
up the new key version on their next cold-start (Secret Manager `version = latest`).
To force an immediate refresh:

```bash
gcloud run services update-traffic <service-name> \
  --to-latest \
  --project="$PROJECT" \
  --region=us-central1
```

### Step 8 — Disable the old Secret Manager key version

Once all services are confirmed healthy and re-encryption is complete:

```bash
gcloud secrets versions disable <old-version-number> \
  --secret=phi-encryption-key \
  --project="$PROJECT"
```

### Rollback

If re-encryption fails and some rows cannot be decrypted:

1. Do NOT disable the old key version.
2. Re-enable the old key version as the active version (add a new Secret Manager
   version with the old key value so it becomes `latest`).
3. Contact the security team to assess which rows need manual intervention.
4. File an incident report per HIPAA breach notification requirements.

### Security Audit Log

All re-encryption runs must be recorded manually in the audit log:

| Field | Value |
|-------|-------|
| Date | ISO-8601 datetime |
| Operator | Name and GCP identity |
| Old key version | Secret Manager version number |
| New key version | Secret Manager version number |
| Tables processed | patient, document, chatbot_transcript |
| Rows re-encrypted | Total count from script output |
| Dry-run first? | Yes / No |
| Outcome | Success / Partial / Rollback |
