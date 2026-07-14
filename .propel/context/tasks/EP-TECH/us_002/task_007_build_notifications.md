---
task_id: task_007
story_id: us_002
epic: EP-TECH
title: Build Notifications — Slack and Email Alerts on Pipeline Success/Failure
layer: Developer Experience
effort_hours: 1
sequence: 7
status: Draft
---

# TASK-007: Build Notifications — Slack and Email Alerts on Pipeline Success/Failure

> **Story:** EP-TECH/US-002 | **Layer:** Developer Experience | **Effort:** 1 hour | **Seq:** 7 of 7

## Objective

Configure Cloud Build notifications so the development team receives Slack messages and email alerts for build success, build failure, canary rollback, and prod deployment approval requests — satisfying AC-4 without requiring a separate notification service beyond what Cloud Build provides natively.

## Implementation Steps

### 1. Cloud Build Notifier — Slack (`notifications/slack-notifier.yaml`)

Cloud Build provides a prebuilt Slack notifier container. Deploy it as a Cloud Run service:

```yaml
# notifications/slack-notifier.yaml
# Deploy using: gcloud run services replace notifications/slack-notifier.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: build-slack-notifier
  namespace: smarthandoff-staging
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "1"
    spec:
      containers:
        - image: us-east1-docker.pkg.dev/gcb-release/cloud-build-notifiers/slack:latest
          name: slack-notifier
          envFrom:
            - secretRef:
                name: slack-webhook-url  # Secret Manager reference
          env:
            - name: CONFIG_PATH
              value: gs://smarthandoff-tf-state-staging/notifier-config/slack.yaml
            - name: PROJECT_ID
              value: smarthandoff-staging
```

**Slack Notifier Config** (`gs://smarthandoff-tf-state-staging/notifier-config/slack.yaml`):

```yaml
apiVersion: cloud-build-notifiers/v1
kind: SlackNotifier
metadata:
  name: smarthandoff-slack-notifier
spec:
  notification:
    filter: |
      build.status == Build.Status.SUCCESS
      || build.status == Build.Status.FAILURE
      || build.status == Build.Status.CANCELLED
      || build.status == Build.Status.TIMEOUT
    delivery:
      webhookUrl:
        secretRef: slack-webhook-url-secret
    template:
      type: golang
      uri: gs://smarthandoff-tf-state-staging/notifier-config/slack_template.json
  secrets:
    - name: slack-webhook-url-secret
      value: projects/smarthandoff-staging/secrets/smarthandoff-slack-webhook-url-staging/versions/latest
```

**Slack Message Template** (`notifications/slack_template.json`):

```json
{
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "{{if eq .Build.Status.String \"SUCCESS\"}}✅{{else if eq .Build.Status.String \"FAILURE\"}}❌{{else}}⚠️{{end}} *SmartHandoff Build {{.Build.Status.String}}*"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Build ID:*\n<{{.Build.LogUrl}}|{{.Build.Id}}>"
        },
        {
          "type": "mrkdwn",
          "text": "*Trigger:*\n{{.Build.Substitutions._ENVIRONMENT}}"
        },
        {
          "type": "mrkdwn",
          "text": "*Commit:*\n`{{.Build.Substitutions.SHORT_SHA}}`"
        },
        {
          "type": "mrkdwn",
          "text": "*Duration:*\n{{duration .Build.StartTime .Build.FinishTime}}"
        }
      ]
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {"type": "plain_text", "text": "View Logs"},
          "url": "{{.Build.LogUrl}}"
        }
      ]
    }
  ]
}
```

### 2. Email Notifications via Cloud Build Built-In

Cloud Build natively supports email notifications via the GCP Alert channel configured in Task 009 (monitoring). Add email notification directly to the Cloud Build trigger:

```hcl
# In Terraform — Cloud Build trigger with notification
resource "google_cloudbuild_trigger" "main_pipeline" {
  # ... existing config ...

  # Cloud Build automatically sends build status to Cloud Monitoring
  # which forwards to the email notification channel configured in monitoring module
}
```

Additionally, for more granular control, add an explicit notification step at the end of the pipeline:

```yaml
# Add to .cloudbuild/build.yaml — final step (always runs, even on failure)
- id: notify-build-result
  name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
  entrypoint: bash
  args:
    - -c
    - |
      STATUS="${_BUILD_STATUS:-UNKNOWN}"
      SHA="$_SHORT_SHA"
      BUILD_URL="https://console.cloud.google.com/cloud-build/builds/$BUILD_ID?project=$PROJECT_ID"

      # Format message based on status
      if [ "$STATUS" = "SUCCESS" ]; then
        EMOJI="✅"; COLOR="good"
      else
        EMOJI="❌"; COLOR="danger"
      fi

      PAYLOAD=$(cat <<EOF
      {
        "text": "$EMOJI SmartHandoff CI/CD: *$STATUS*",
        "attachments": [{
          "color": "$COLOR",
          "fields": [
            {"title": "Commit", "value": "$SHA", "short": true},
            {"title": "Environment", "value": "$_ENVIRONMENT", "short": true},
            {"title": "Build ID", "value": "<$BUILD_URL|$BUILD_ID>", "short": false}
          ]
        }]
      }
      EOF
      )

      # Send to Slack webhook (URL from Secret Manager)
      WEBHOOK=$(gcloud secrets versions access latest \
        --secret="smarthandoff-slack-webhook-url-$_ENVIRONMENT" \
        --project="$PROJECT_ID" 2>/dev/null || echo "")

      if [ -n "$WEBHOOK" ]; then
        curl -sS -X POST "$WEBHOOK" \
          -H "Content-Type: application/json" \
          -d "$PAYLOAD"
        echo "Slack notification sent"
      else
        echo "No Slack webhook configured — skipping notification"
      fi
  # Run even if previous steps failed
  waitFor: ['create-cloud-deploy-release', 'vulnerability-scan-gate']
  allowFailure: true  # Don't fail the build if notification fails
```

### 3. Cloud Deploy Approval Notification

When a prod rollout requires approval (AC-5), Cloud Deploy sends a notification. Add the team email to Cloud Deploy's approval notification:

```hcl
# In Terraform — Cloud Deploy approval notification channel
resource "google_clouddeploy_delivery_pipeline" "service_pipelines" {
  for_each = toset(local.services)

  # ... existing pipeline config ...

  annotations = {
    "clouddeploy.googleapis.com/approval-notification-emails" = var.oncall_email
  }
}
```

### 4. Add Slack Webhook Secret to Secret Manager (Terraform)

```hcl
resource "google_secret_manager_secret" "slack_webhook" {
  secret_id = "smarthandoff-slack-webhook-url-${var.environment}"
  project   = var.project_id
  replication { auto {} }
}

resource "google_secret_manager_secret_version" "slack_webhook" {
  secret      = google_secret_manager_secret.slack_webhook.id
  secret_data = "PLACEHOLDER_REPLACE_WITH_REAL_SLACK_WEBHOOK_URL"
}
```

> SecOps replaces the placeholder with the actual Slack incoming webhook URL from the team's Slack workspace settings.

### 5. Verify Notification Flow

Manual test procedure:
1. Push a commit with a deliberate lint error to a feature branch
2. Create a PR → verify no notification (PR builds are for Terraform validation only)
3. Merge a good commit to `main` → verify ✅ Slack message within 5 minutes of build completion
4. Push a commit that fails the `bandit` SAST check → verify ❌ Slack message

## Acceptance Criteria

- [ ] **AC-4 satisfied:** Slack message received within 5 minutes of a successful `main` branch build completing — verified by inspecting Slack channel
- [ ] **AC-4 satisfied:** Slack message received within 5 minutes of a build failure — verified by introducing a deliberate test failure
- [ ] Slack message includes: build status emoji, commit SHA, environment, and link to Cloud Build logs
- [ ] Prod approval request email sent to `oncall_email` when a Cloud Deploy prod rollout is pending approval — verified by creating a manual release targeting prod
- [ ] Notification step has `allowFailure: true` — confirmed by killing the Slack webhook URL and verifying the pipeline itself still passes/fails based on actual code quality

## Files to Create

```
notifications/slack-notifier.yaml
notifications/slack_template.json
notifications/slack.yaml.template           (config template — actual stored in GCS)
infra/terraform/modules/secrets/slack.tf    (add Slack webhook secret)
```

## Files to Update

```
.cloudbuild/build.yaml                      (add notify-build-result step)
infra/terraform/modules/cloud_deploy/main.tf (add approval email annotation)
```

## Notes

- `allowFailure: true` on the notification step is critical — a Slack API failure should never cause a deployment failure
- The Slack webhook URL is treated as a secret (stored in Secret Manager) even though it doesn't grant access to systems — it can be used to spam the Slack channel if leaked
- Cloud Build's built-in Pub/Sub topic (`cloud-builds`) can be used to trigger more sophisticated notification workflows via Cloud Functions if needed in the future
- Cloud Deploy's approval email is sent by Google's infrastructure — no additional configuration needed beyond the email annotation on the pipeline
