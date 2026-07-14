---
id: TASK-002
title: "Mount Secret Manager Secrets as Environment Variables in Cloud Run Services"
user_story: US-001
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-002: Mount Secret Manager Secrets as Environment Variables in Cloud Run Services

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

`infra/terraform/modules/cloud_run/main.tf` contains the following deferred comment:

> *"Non-sensitive runtime config; secrets are mounted via Secret Manager bindings added in Task 008 (us_001) once all secrets are defined."*

Without this step, Cloud Run services would either have no credentials at runtime (causing startup failures) or would require plaintext secrets in environment variables (violating **Acceptance Criterion 4**). This task resolves that deferred work by adding Secret Manager `value_source` bindings to every service container definition.

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 4** | `When` Cloud Run service environment variables and container image layers are inspected, `Then` zero plaintext secrets are found; all secrets are mounted from Secret Manager |

---

## Implementation Steps

### 1. Add Service-to-Secret Mapping `locals` in `cloud_run/main.tf`

```hcl
locals {
  # Maps each service to the Secret Manager secret keys it requires.
  # Secret names follow the convention: smarthandoff-<key>-<environment>
  # NOTE: db-password is managed by the cloud_sql module; its name is
  #       "smarthandoff-db-password-<environment>" — referenced directly here.
  service_secrets = {
    "api-gateway" = [
      "db-password", "redis-auth-token", "jwt-signing-key"
    ]
    "hl7-listener" = [
      "hl7-mllp-signing-key"
    ]
    "coordinator-agent" = [
      "db-password", "fhir-api-key", "vertex-ai-api-key"
    ]
    "docs-agent" = [
      "db-password", "fhir-api-key"
    ]
    "medrecon-agent" = [
      "db-password", "fhir-api-key"
    ]
    "bed-mgmt-agent" = [
      "db-password"
    ]
    "followup-agent" = [
      "db-password"
    ]
    "comms-agent" = [
      "db-password", "twilio-auth-token", "sendgrid-api-key"
    ]
    "ml-inference" = [
      "vertex-ai-api-key", "redis-auth-token"
    ]
    "notification-svc" = [
      "twilio-auth-token", "sendgrid-api-key"
    ]
  }

  # Derive the env var name from the secret key (e.g., "db-password" → "DB_PASSWORD")
  secret_env_var_name = {
    "db-password"          = "DB_PASSWORD"
    "redis-auth-token"     = "REDIS_AUTH_TOKEN"
    "jwt-signing-key"      = "JWT_SIGNING_KEY"
    "fhir-api-key"         = "FHIR_API_KEY"
    "twilio-auth-token"    = "TWILIO_AUTH_TOKEN"
    "sendgrid-api-key"     = "SENDGRID_API_KEY"
    "hl7-mllp-signing-key" = "HL7_MLLP_SIGNING_KEY"
    "vertex-ai-api-key"    = "VERTEX_AI_API_KEY"
  }
}
```

### 2. Add `dynamic "env"` Secret Bindings in the `google_cloud_run_v2_service` Container Block

Inside the `containers` block of `google_cloud_run_v2_service.services`, after the existing `env` blocks for `ENVIRONMENT`, `GCP_PROJECT_ID`, and `REGION`, add:

```hcl
dynamic "env" {
  for_each = lookup(local.service_secrets, each.key, [])
  content {
    name = local.secret_env_var_name[env.value]
    value_source {
      secret_key_ref {
        secret  = "smarthandoff-${env.value}-${var.environment}"
        version = "latest"
      }
    }
  }
}
```

> **Note on `depends_on`**: The `google_cloud_run_v2_service` resource must declare `depends_on = [google_service_account.cloud_run_sa]`. Add the secrets module IAM bindings to this list when the environment root wires the modules together (handled in TASK-003).

### 3. Update `ignore_changes` in `lifecycle` Block

The `lifecycle` block already ignores `image`. Extend it to also ignore secret version references so that secret rotations triggered outside Terraform (e.g., CI/CD secret rotation) do not cause Terraform drift:

```hcl
lifecycle {
  ignore_changes = [
    template[0].containers[0].image,
    # Secret versions are rotated outside Terraform via Cloud KMS rotation policy.
    # Terraform should not revert to "latest" on every plan.
    template[0].containers[0].env,
  ]
}
```

> **Security note**: Using `version = "latest"` ensures newly rotated secrets are automatically picked up on the next Cloud Run revision deploy without a Terraform change.

---

## Definition of Done

- [ ] `cloud_run/main.tf` `locals` block defines `service_secrets` and `secret_env_var_name` maps
- [ ] `dynamic "env"` block adds one `value_source.secret_key_ref` env var per secret per service
- [ ] No service has a `DB_PASSWORD`, `JWT_SIGNING_KEY`, `REDIS_AUTH_TOKEN`, or any other credential as a plain `value` string
- [ ] `terraform validate` passes for the `cloud_run` module
- [ ] `terraform plan` (after TASK-003 wires the secrets module) shows the env bindings for all 10 services
- [ ] `lifecycle.ignore_changes` covers `env` to prevent rotation drift

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Preceding task | Secret Manager secrets must be defined before Cloud Run can reference them |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/modules/cloud_run/main.tf` | Add `service_secrets` + `secret_env_var_name` locals; add `dynamic "env"` block; extend `ignore_changes` |
