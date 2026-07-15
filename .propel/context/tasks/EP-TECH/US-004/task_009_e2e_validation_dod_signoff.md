---
id: TASK-009
title: "End-to-End Observability Validation and DoD Signoff"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: Validation
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008]
---

# TASK-009: End-to-End Observability Validation and DoD Signoff

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

With all infrastructure (TASK-001 through TASK-005) and application observability (TASK-006 through TASK-008) implemented, this task validates every Acceptance Criterion and Definition of Done item before marking US-004 complete.

Validation is performed against the `dev` environment after a full `terraform apply` of the `monitoring` module and after deploying the updated services with OTel/logging integration active.

---

## Acceptance Criteria Validated

| Scenario | Requirement | Validation Method |
|---|---|---|
| **Scenario 1** | P1 alert fires within 2 minutes on error rate >1% | Inject synthetic 5xx errors; verify PagerDuty/email fires ≤2 min |
| **Scenario 2** | Single end-to-end trace in Cloud Trace for ADT A01 event | Send test HL7 ADT A01 via MLLP; inspect trace in Cloud Trace |
| **Scenario 3** | Uptime check detects non-2xx `/health` and fires alert | Stop one service; observe uptime alert fires within 2 check cycles |
| **Scenario 4** | PHI fields replaced with `[REDACTED]` in standard logs | Log message with MRN; inspect Cloud Logging `_Default` bucket |

---

## Validation Steps

### Step 1: Terraform Apply — `dev` Environment

```bash
cd infra/terraform/environments/dev
terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

**Expected output:**

```
Apply complete! Resources: X added, 0 changed, 0 destroyed.

Outputs:
  email_notification_channel_id    = "projects/<project>/notificationChannels/<id>"
  pagerduty_notification_channel_id = (sensitive value)
  p1_error_rate_alert_policy_id    = "projects/<project>/alertPolicies/<id>"
  p2_latency_alert_policy_id       = "projects/<project>/alertPolicies/<id>"
  p3_dlq_alert_policy_id           = "projects/<project>/alertPolicies/<id>"
  uptime_check_ids                 = { "api-gateway" = "...", ... }
  dashboard_url                    = "https://console.cloud.google.com/monitoring/dashboards/..."
  audit_log_bucket_name            = "smarthandoff-audit-logs-dev-<project-id>"
```

### Step 2: Validate Alert Policies (Scenario 1)

**Test P1 — Error Rate Alert:**

```bash
# Inject synthetic 5xx responses for 90 seconds using a load test against api-gateway
# (use a test endpoint that intentionally returns 500 for this validation only)
for i in $(seq 1 100); do
  curl -s -o /dev/null -w "%{http_code}" https://api-gateway.dev.<api_domain>/test/force-error
done
```

- Monitor Cloud Monitoring → Alert Policies → `[P1] SmartHandoff — Error Rate >1%`
- Verify alert transitions to `FIRING` state within 2 minutes
- Verify email notification received at oncall inbox
- Verify PagerDuty incident created

**Checklist:**
- [ ] P1 alert shows `FIRING` in Cloud Monitoring console
- [ ] Email notification received within 2 minutes
- [ ] PagerDuty incident created within 2 minutes

### Step 3: Validate End-to-End Distributed Trace (Scenario 2)

**Send a test HL7 ADT A01 message via MLLP:**

```bash
# Use mllp_client (Python package) to send a minimal ADT A01 to hl7-listener
python -c "
import mllp_client
msg = (
  'MSH|^~\&|TEST|TEST|||$(date +%Y%m%d%H%M%S)||ADT^A01|MSG001|P|2.5\r'
  'EVN|A01|$(date +%Y%m%d%H%M%S)\r'
  'PID|||TEST-MRN-001||Smith^John||19800101|M\r'
  'PV1|1|I|WARD1^BED1^ROOM1\r'
)
mllp_client.send('hl7-listener.dev.<api_domain>', 2575, msg)
"
```

**Inspect trace in Cloud Trace:**
1. Open Cloud Console → Cloud Trace → Trace List
2. Filter by service name `hl7-listener`, time range: last 5 minutes
3. Click on the trace for the test ADT A01 event
4. Verify the following spans are present with correct parent-child nesting:

```
hl7-listener.process_adt_message (root)
  └── coordinator-agent.process_adt_event
        ├── docs-agent.process_adt_event
        └── medrecon-agent.process_adt_event
              └── notification-svc (SignalR push span)
```

**Checklist:**
- [ ] Single trace ID visible across all 10 services in Cloud Trace
- [ ] Parent-child span relationships correct (hl7-listener → coordinator → agents)
- [ ] Each span shows service name, latency, and status
- [ ] Total end-to-end trace latency visible from MLLP receipt to SignalR push

### Step 4: Validate Uptime Checks (Scenario 3)

**Stop one service to trigger uptime check failure:**

```bash
# Scale hl7-listener to 0 instances in dev (temporarily)
gcloud run services update hl7-listener --min-instances=0 --max-instances=0 --region=<region> --project=<project_id>
```

- Wait 120 seconds (2 check cycles at 60-second interval)
- Verify uptime alert `[P1] SmartHandoff — Uptime Check Failure` fires in Cloud Monitoring
- Verify Cloud Monitoring dashboard shows `hl7-listener` as failing
- Restore service: `gcloud run services update hl7-listener --min-instances=1 --region=<region>`

**Checklist:**
- [ ] Uptime alert fires after 2 consecutive non-2xx checks
- [ ] Dashboard shows affected service as failing
- [ ] Service restores to passing state after scale-up

### Step 5: Validate PHI Redaction (Scenario 4)

**Trigger a log entry containing PHI from the api-gateway:**

```bash
# Call a test endpoint that logs a request with MRN in the log message
curl -H "Authorization: Bearer <test-token>" \
  "https://api-gateway.dev.<api_domain>/test/log-phi?mrn=12345678&patient_name=John+Smith"
```

**Inspect Cloud Logging — `_Default` bucket:**
1. Open Cloud Console → Cloud Logging → Logs Explorer
2. Filter: `resource.type="cloud_run_revision" AND resource.labels.service_name="api-gateway"`
3. Search for log entries from the test timestamp

**Expected result:** The log entry shows `"mrn": "[REDACTED]"` and `"patient_name": "[REDACTED]"` in the JSON payload — not the raw values.

**Inspect the secure audit bucket:**
1. Open Cloud Console → Cloud Storage → `smarthandoff-audit-logs-dev-<project-id>`
2. Navigate to the log export for the same timestamp
3. Confirm the raw values (`mrn=12345678`) are present in the audit bucket export

**Checklist:**
- [ ] Standard Cloud Logging (`_Default`) shows `[REDACTED]` for PHI fields
- [ ] Secure audit GCS bucket retains original field values
- [ ] Only compliance officer accounts can read the audit bucket (verify with `gcloud storage buckets get-iam-policy`)

### Step 6: Code Review Checklist

Before marking US-004 Done:

- [ ] Terraform: `terraform validate` and `terraform plan` reviewed by a second engineer
- [ ] No secrets in `.tfvars` files or Terraform state — PagerDuty key sourced from Secret Manager
- [ ] Python shared libraries (`shared/otel/`, `shared/logging/`) reviewed and approved
- [ ] PHI regex patterns in `PhiRedactionFilter` reviewed by security lead
- [ ] OTel package versions pinned and consistent across all 10 services
- [ ] All 10 services emit JSON-formatted logs (verified locally)
- [ ] PR contains no commented-out debug code or placeholder `TODO` statements

---

## Definition of Done — Final Checklist

- [ ] Cloud Monitoring dashboards live: service health, ADT throughput, agent latency, error rates
- [ ] P1 alert (error rate >1% / 60s), P2 (latency p95 >5s), P3 (DLQ >0) all configured
- [ ] Uptime checks active for all 10 service `/health` endpoints (60s interval)
- [ ] OpenTelemetry SDK integrated in all 10 services; end-to-end trace visible in Cloud Trace
- [ ] Structured JSON logging with PHI redaction active in all services
- [ ] Alert notification channels (email + PagerDuty) configured and smoke-tested
- [ ] Code reviewed and approved by second engineer
