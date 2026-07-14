---
id: TASK-008
title: "Pipeline Validation — End-to-End Run, Duration Gate, and US-003 Definition of Done Sign-Off"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: Engineering Process
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: Senior DevOps Engineer (Reviewer)
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007]
---

# TASK-008: Pipeline Validation — End-to-End Run, Duration Gate, and US-003 Definition of Done Sign-Off

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Engineering Process | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

This is the final gate task for US-003. It validates that all preceding tasks are complete, all four acceptance scenarios pass end-to-end, and a senior DevOps engineer has formally signed off on the pull request. No CI/CD pipeline configuration from US-003 may merge to `main` without this sign-off.

The DoD explicitly requires:

> *"Pipeline duration <15 minutes for a standard service"*
> *"CRITICAL/HIGH CVEs block deployment; MEDIUM/LOW produce warnings only"*
> *"Code reviewed and approved"*

---

## Acceptance Criteria Addressed

All four scenarios of US-003 are verified end-to-end through the checklist below.

---

## Validation Scenarios

### Scenario 1: Full Pipeline Runs on Push to `main`

**Test procedure:**

1. Push a commit to `main` on the `api-gateway` service with a trivial change (e.g., update a comment).
2. Observe the Cloud Build trigger `smarthandoff-api-gateway-main-push-dev` fires within 60 seconds.
3. Verify stage execution order in the Cloud Build history UI:

| Stage | Step ID | Expected Result |
|---|---|---|
| Lint | `lint-python` / `lint-js` | Green (exit 0) |
| Unit Tests | `test-python` / `test-js` | Green (exit 0) |
| Docker Build | `docker-build` | Image built, tagged with `$COMMIT_SHA` |
| Artifact Registry Push | `artifact-registry-push-sha` | Image visible in Artifact Registry |
| Trivy Scan | `trivy-scan-critical-high` | Green (no CRITICAL/HIGH CVEs) |
| SARIF Upload | `upload-sarif-to-scc` | SARIF visible in Cloud SCC |
| Deploy Revision | `deploy-new-revision` | New revision deployed with `--no-traffic` |
| Canary Traffic | `canary-traffic-split` | 10% traffic on new revision confirmed |
| Observation Window | `canary-observation-window` | 5-minute window passes, no alert fired |
| Full Promotion | `promote-full-traffic` | 100% traffic on new revision confirmed |

4. Verify total build duration is **< 15 minutes** (check Cloud Build `duration` field in the build record).

**Pass criteria:** All 10 stages complete with exit code 0; build duration ≤ 900 seconds.

---

### Scenario 2: Vulnerability Scan Blocks Deployment on CRITICAL CVE

**Test procedure:**

1. Temporarily add a known-vulnerable base image to `services/api-gateway/Dockerfile` (e.g., `FROM python:3.6-slim` — contains numerous CRITICAL CVEs).
2. Push to `main`.
3. Verify the pipeline fails at the `trivy-scan-critical-high` step with a non-zero exit code.
4. Verify **no new Cloud Run revision is deployed** (`deploy-new-revision` step must NOT run).
5. Verify a Slack/email alert is received by the DevOps team notifier (from TASK-003).
6. Revert the Dockerfile change.

**Pass criteria:** Build status = FAILURE; step `deploy-new-revision` absent from completed steps; Slack alert received.

---

### Scenario 3: Canary Rollback on Error Rate Spike

**Test procedure:**

1. Deploy a canary revision that intentionally returns 5xx on >1% of requests (e.g., inject a route that returns HTTP 500 on `/health`).
2. Wait for the canary traffic split (10%) to activate.
3. Generate synthetic load against the service (using `hey` or `wrk`) to trigger the error threshold.
4. Verify within 5 minutes that:
   - The Cloud Monitoring alert policy `smarthandoff-api-gateway-canary-error-rate-dev` enters the OPEN state.
   - The rollback `cloudbuild-rollback.yaml` trigger fires.
   - 100% traffic is re-routed to the previous stable revision.
   - The pipeline build is marked FAILURE.
5. Verify Slack rollback notification is received.

**Pass criteria:** Alert fires within 5-minute window; traffic restored to previous revision within 60 seconds of trigger firing; build marked FAILED; Slack notification received.

---

### Scenario 4: Secrets Never Appear in Pipeline Logs

**Test procedure:**

1. Navigate to **Cloud Logging → Logs Explorer**.
2. Query:
```
resource.type="build"
logName=~"logs/cloudbuild"
textPayload=~"(?i)(api_key|apikey|password|secret|token|credential|sk-)[^=\s]*=\S+"
```
3. Verify **zero log entries** match.
4. Review the secrets audit report from TASK-007.

**Pass criteria:** Zero log entries containing secret-shaped patterns; TASK-007 sign-off present in PR.

---

## Review Checklist

### Pipeline Configuration (DoD Items 1–2)

| Item | Verified by |
|---|---|
| Cloud Build trigger exists for all 10 services (dev, staging, prod) | Terraform state (`terraform show`) |
| `cloudbuild-shared.yaml` defines lint (flake8 + eslint) and unit test (pytest + jest) stages | Code review |
| Per-service `cloudbuild.yaml` defines all 9 stages in correct order | Code review |
| `timeout: '900s'` set on all `cloudbuild.yaml` files | `grep -r timeout services/*/cloudbuild.yaml` |

### Canary Deployment (DoD Item 3)

| Item | Verified by |
|---|---|
| `--no-traffic` used on initial `gcloud run deploy` | Code review |
| `--to-revisions=NEW=10` used for canary split | Code review |
| `--to-revisions=NEW=100` used for full promotion | Code review |
| 5-minute observation window implemented | Code review |

### Automated Rollback (DoD Item 4)

| Item | Verified by |
|---|---|
| Alert policy created for all 10 services | Terraform state / GCP Console |
| Alert threshold = 1% 5xx error rate, 5-minute window | Terraform code review |
| `auto_close = "1800s"` on alert policy | Terraform code review |
| Pub/Sub notification channel wired to alert policy | Terraform state |
| `cicd-alert-handler` Cloud Run service deployed | GCP Console |
| Rollback trigger fired and traffic restored in Scenario 3 test | Manual validation |

### Pipeline Duration (DoD Item 5)

| Item | Verified by |
|---|---|
| Standard service pipeline completes in < 15 minutes | Build history `duration` field |
| Trivy DB cache bucket exists with 7-day lifecycle | Terraform state |

### CVE Severity Gating (DoD Item 6)

| Item | Verified by |
|---|---|
| `--exit-code 1 --severity CRITICAL,HIGH` blocks deployment | Scenario 2 test |
| `--exit-code 0 --severity MEDIUM,LOW` produces warning only | Code review |
| SARIF output visible in Cloud SCC | Cloud SCC console |

### Secrets Security (Scenario 4 / HIPAA)

| Item | Verified by |
|---|---|
| `CLOUD_LOGGING_ONLY` set on all pipeline configs | Static scan (TASK-007) |
| Zero secrets in Cloud Build logs | Log scan (TASK-007) |
| All runtime secrets use `secretEnv` binding | Code review (TASK-007) |
| Dockerfile ARG audit: zero secret-shaped ARGs | Static scan (TASK-007) |
| `.cloudbuild/secrets-audit-report.md` signed off | PR attachment |

### Code Review (DoD Item 7)

- [ ] PR opened targeting `main` branch
- [ ] All 7 preceding tasks (TASK-001 through TASK-007) have their DoD checklists fully checked
- [ ] TASK-007 secrets audit report attached to PR
- [ ] Scenario 1 build duration screenshot attached to PR (shows < 15 min)
- [ ] Scenario 2 FAILURE screenshot attached to PR
- [ ] Scenario 3 rollback Slack notification screenshot attached to PR
- [ ] Senior DevOps engineer approval recorded on PR

---

## Definition of Done Checklist

- [ ] Scenario 1 verified: full 9-stage pipeline completes in < 15 minutes on `api-gateway` service
- [ ] Scenario 2 verified: CRITICAL CVE build fails at scan stage, no revision deployed, alert sent
- [ ] Scenario 3 verified: canary error spike triggers rollback within 5-minute window
- [ ] Scenario 4 verified: zero secret-shaped strings in Cloud Build logs
- [ ] All DoD items from TASK-001 through TASK-007 confirmed complete
- [ ] PR approved by Senior DevOps Engineer and merged to `main`
