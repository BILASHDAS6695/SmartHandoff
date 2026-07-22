---
id: TASK-007
title: "Secrets Audit — Verify No Plaintext Secrets or Credentials in Cloud Build Logs"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: Security / Validation
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-007: Secrets Audit — Verify No Plaintext Secrets or Credentials in Cloud Build Logs

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Security / Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-003 Scenario 4 is a hard HIPAA security requirement:

> *"No plaintext secrets, API keys, or database credentials appear in any log line; all secrets are sourced from Secret Manager at runtime."*

This task performs a structured audit of every Cloud Build step across all `cloudbuild.yaml` files to confirm that:

1. No `--env` flag passes a secret value directly.
2. No `echo`, `print`, or `cat` command outputs a secret-shaped string.
3. All runtime secrets are sourced via `gcloud secrets versions access` or mounted via the Cloud Build `secretEnv` mechanism.
4. `CLOUD_LOGGING_ONLY` is set on all pipeline configs.

This audit must be completed and signed off before the pipeline is promoted to staging or production.

---

## Acceptance Criteria Addressed

| US-003 AC | Requirement |
|---|---|
| **Scenario 4** | `Given` the CI/CD pipeline runs `When` Cloud Build logs are reviewed `Then` no plaintext secrets, API keys, or database credentials appear in any log line |

---

## Implementation Steps

### 1. Static Analysis — Scan All `cloudbuild.yaml` Files

Run a static scan across all pipeline YAML files to detect patterns that could leak secrets:

```bash
# Scan for common secret leakage patterns
grep -rn \
  -e 'echo.*KEY\|echo.*SECRET\|echo.*TOKEN\|echo.*PASSWORD\|echo.*CREDENTIAL' \
  -e '\-\-env.*=.*KEY\|--env.*=.*SECRET\|--env.*=.*TOKEN' \
  -e 'cat.*\.env\|cat.*secrets\|cat.*credentials' \
  services/*/cloudbuild.yaml \
  .cloudbuild/*.yaml \
  cloudbuild-shared.yaml

echo "Exit code: $? (0 = no matches found = PASS)"
```

Expected result: **zero matches**. Any match is a blocker that must be resolved before sign-off.

### 2. Verify `CLOUD_LOGGING_ONLY` on All Pipeline Configs

```bash
# Every cloudbuild.yaml must have logging: CLOUD_LOGGING_ONLY
FILES_WITHOUT_LOG_SETTING=$(grep -rL 'CLOUD_LOGGING_ONLY' services/*/cloudbuild.yaml .cloudbuild/*.yaml 2>/dev/null)
if [ -n "$FILES_WITHOUT_LOG_SETTING" ]; then
  echo "FAIL: The following files are missing CLOUD_LOGGING_ONLY:"
  echo "$FILES_WITHOUT_LOG_SETTING"
  exit 1
fi
echo "PASS: All pipeline files have CLOUD_LOGGING_ONLY set"
```

### 3. Verify All Secrets Are Sourced from Secret Manager

Any step that needs a runtime secret **must** use the Cloud Build `availableSecrets` + `secretEnv` mechanism rather than hardcoded substitutions:

**Correct pattern (Secret Manager binding):**

```yaml
availableSecrets:
  secretManager:
    - versionName: projects/${_PROJECT_ID}/secrets/slack-cicd-webhook/versions/latest
      env: 'SLACK_WEBHOOK_URL'

steps:
  - name: 'gcr.io/cloud-builders/curl'
    secretEnv: ['SLACK_WEBHOOK_URL']
    args: ['-X', 'POST', '$SLACK_WEBHOOK_URL', '--data', '...']
```

**Forbidden pattern (direct substitution of secret value):**

```yaml
substitutions:
  _SLACK_WEBHOOK: 'https://hooks.slack.com/services/T.../B.../XXXXX'  # FORBIDDEN
steps:
  - name: '...'
    args: ['...', '${_SLACK_WEBHOOK}']  # FORBIDDEN
```

Audit all 10 `cloudbuild.yaml` files and `.cloudbuild/cloudbuild-rollback.yaml` for forbidden patterns. For any step that currently uses a direct substitution for a secret value:

1. Add the secret to Secret Manager (ensure the `secrets` Terraform module from US-001 TASK-001 covers it, or create it manually).
2. Replace the substitution with a `secretEnv` binding.
3. Verify the Cloud Build service account has `roles/secretmanager.secretAccessor` for the secret (already granted in TASK-006).

### 4. Audit Dockerfile `ARG` Usage

Scan all `Dockerfile` files for build-time `ARG` declarations that could receive secret values:

```bash
grep -rn 'ARG.*KEY\|ARG.*SECRET\|ARG.*TOKEN\|ARG.*PASSWORD' services/*/Dockerfile
```

If any matches are found:
- Remove the `ARG` from the `Dockerfile`.
- Move secret consumption to container startup (read from Secret Manager via the service's runtime identity).
- Verify no corresponding `--build-arg` in the `docker build` step passes a secret value (already checked in TASK-002).

### 5. Cloud Logging Log Scan (Post-Pipeline Execution)

After a full pipeline run completes (from TASK-008), perform a log query in Cloud Logging to verify no secret-shaped strings appear in any build log:

```bash
# Query Cloud Logging for potential secret leakage in Cloud Build logs
gcloud logging read \
  'resource.type="build" AND logName=~"logs/cloudbuild" AND (
    textPayload=~"[A-Za-z0-9+/]{40,}={0,2}" OR
    textPayload=~"(?i)(api_key|apikey|api-key|password|passwd|secret|token|credential)[^=]*=\S+" OR
    textPayload=~"sk-[a-zA-Z0-9]{20,}" OR
    textPayload=~"ya29\.[a-zA-Z0-9_\-]+"
  )' \
  --project=${PROJECT_ID} \
  --limit=50 \
  --format=json
```

Expected result: **zero log entries** matching these patterns. Any match requires immediate investigation, step remediation, and re-run.

### 6. Secret Manager Access Log Review

Verify that secrets are accessed at runtime (not build time) by checking Secret Manager audit logs:

```bash
gcloud logging read \
  'resource.type="audited_resource" AND protoPayload.serviceName="secretmanager.googleapis.com" AND protoPayload.methodName="AccessSecretVersion"' \
  --project=${PROJECT_ID} \
  --limit=20 \
  --format="table(timestamp, protoPayload.authenticationInfo.principalEmail, protoPayload.resourceName)"
```

The `principalEmail` should show the Cloud Run service account (runtime access), not the Cloud Build service account (build-time access). If Cloud Build SA appears accessing application secrets (not the `slack-cicd-webhook`), investigate and remediate.

---

## Files Produced

| File | Action |
|---|---|
| `.cloudbuild/secrets-audit-report.md` | Create — document audit findings and sign-off |
| `services/<service>/cloudbuild.yaml` (as needed) | Update — replace forbidden substitution patterns with `secretEnv` bindings |

---

## Definition of Done Checklist

- [ ] Static scan returns zero matches for secret leakage patterns across all pipeline YAML files
- [ ] All pipeline configs confirmed to have `logging: CLOUD_LOGGING_ONLY`
- [ ] All runtime secrets use `availableSecrets.secretManager` + `secretEnv` — no direct substitution of secret values
- [ ] Dockerfile ARG audit returns zero secret-shaped ARG declarations
- [ ] Cloud Logging post-pipeline log scan returns zero matches for secret-shaped patterns
- [ ] Secret Manager audit log shows only runtime service accounts accessing application secrets
- [ ] `.cloudbuild/secrets-audit-report.md` created and signed off by security reviewer
