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
