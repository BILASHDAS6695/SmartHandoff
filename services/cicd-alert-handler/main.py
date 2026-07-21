"""
cicd-alert-handler — Cloud Run Pub/Sub push subscriber
Bridges Cloud Monitoring canary error-rate alerts to Cloud Build rollback triggers.

Flow:
  Cloud Monitoring alert (canary error rate >1%)
    → Pub/Sub topic smarthandoff-canary-rollback-<service>-<env>
      → this service (POST /)
        → Cloud Build API: trigger cloudbuild-rollback.yaml

Security:
  - No secrets are logged or printed (US-003 Scenario 4)
  - Uses Application Default Credentials (Workload Identity on Cloud Run)
  - Input validation on all Pub/Sub message fields
"""
import base64
import json
import logging
import os
import re

import google.auth
import google.auth.transport.requests
import requests
from flask import Flask, request, make_response

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Required environment variables (set via Cloud Run environment, not secrets)
PROJECT_ID = os.environ.get("PROJECT_ID", "")
REGION = os.environ.get("REGION", "us-central1")
ROLLBACK_TRIGGER_NAME_PATTERN = "smarthandoff-{service}-rollback-{environment}"

# Input validation: only allow known service names (prevents injection)
VALID_SERVICES = {
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "comms-agent", "ml-inference", "notification-svc",
    "audit-svc", "portal-bff",
}
VALID_ENVIRONMENTS = {"dev", "staging", "prod"}


def _get_access_token() -> str:
    """Obtain a short-lived access token using Application Default Credentials."""
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token


def _extract_service_from_policy(policy_name: str) -> tuple[str, str]:
    """
    Extract (service_name, environment) from a Cloud Monitoring alert policy name.
    Expected format: smarthandoff-<service>-canary-error-rate-<env>
    Returns ("", "") on parse failure.
    """
    # Validate pattern to prevent injection attacks
    pattern = r"^smarthandoff-([a-z0-9-]+)-canary-error-rate-(dev|staging|prod)$"
    match = re.match(pattern, policy_name)
    if not match:
        return "", ""
    service, environment = match.group(1), match.group(2)
    if service not in VALID_SERVICES:
        logger.warning("Unknown service in alert: %s", service)
        return "", ""
    return service, environment


@app.route("/", methods=["POST"])
def handle_alert():
    """Receive Pub/Sub push notification and trigger Cloud Build rollback."""
    # Validate Content-Type
    if not request.is_json:
        logger.error("Invalid content-type: expected application/json")
        return make_response("Bad Request", 400)

    envelope = request.get_json(force=True, silent=True)
    if not envelope or "message" not in envelope:
        logger.error("Missing Pub/Sub message envelope")
        return make_response("Bad Request: missing message", 400)

    # Decode Pub/Sub message data
    try:
        raw_data = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
        incident_payload = json.loads(raw_data)
    except (KeyError, ValueError) as exc:
        logger.error("Failed to decode Pub/Sub message: %s", exc)
        return make_response("Bad Request: invalid message data", 400)

    # Extract policy name from incident (Cloud Monitoring alert format)
    incident = incident_payload.get("incident", {})
    policy_name = incident.get("policy_name", "")
    incident_state = incident.get("state", "")

    # Only act on OPEN incidents (not on auto-close notifications)
    if incident_state != "open":
        logger.info("Ignoring non-open incident state: %s", incident_state)
        return make_response("OK: non-open incident ignored", 200)

    service_name, environment = _extract_service_from_policy(policy_name)
    if not service_name:
        logger.error("Could not extract service from policy name: %s", policy_name)
        return make_response("Bad Request: unrecognised policy name", 400)

    logger.info("Triggering rollback for %s-%s", service_name, environment)

    # Trigger the Cloud Build rollback pipeline
    trigger_name = ROLLBACK_TRIGGER_NAME_PATTERN.format(
        service=service_name, environment=environment
    )
    url = (
        f"https://cloudbuild.googleapis.com/v1/projects/{PROJECT_ID}"
        f"/locations/global/triggers/{trigger_name}:run"
    )
    body = {
        "substitutions": {
            "_SERVICE_NAME": service_name,
            "_ENVIRONMENT": environment,
            "_REGION": REGION,
            "_PROJECT_ID": PROJECT_ID,
        }
    }

    try:
        token = _get_access_token()
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Cloud Build rollback triggered: HTTP %s", resp.status_code)
        return make_response("OK: rollback triggered", 200)
    except requests.RequestException as exc:
        logger.error("Failed to trigger Cloud Build rollback: %s", exc)
        # Return 500 so Pub/Sub retries the delivery
        return make_response("Internal Server Error: Cloud Build trigger failed", 500)


@app.route("/health", methods=["GET"])
def health():
    return make_response('{"status": "ok"}', 200, {"Content-Type": "application/json"})


@app.route("/ready", methods=["GET"])
def ready():
    return make_response('{"status": "ready"}', 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
