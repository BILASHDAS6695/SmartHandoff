---
id: TASK-003
title: "Create `notifications/upload_sendgrid_templates.py` — CI/CD Upload Script + `config/sendgrid_templates.yaml` Template ID Registry"
user_story: US-066
epic: EP-013
sprint: 2
layer: Backend / CI-CD
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Create `notifications/upload_sendgrid_templates.py` — CI/CD Upload Script + `config/sendgrid_templates.yaml` Template ID Registry

> **Story:** US-066 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / CI-CD | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-066 DoD specifies:

> *"CI/CD step: `upload_sendgrid_templates.py` uploads templates to SendGrid API on every deploy"*
> *"Template IDs stored in `config/sendgrid_templates.yaml` (updated by CI/CD upload script)"*
> *"Scenario 3: the updated template JSON is uploaded to SendGrid via `SendGridAPIClient.client.templates.post()`; the previous version is archived in SendGrid"*

This task implements:

1. **`notifications/upload_sendgrid_templates.py`** — idempotent upload script that creates or updates all 6 SendGrid Dynamic Templates and writes the resulting template IDs to `config/sendgrid_templates.yaml`
2. **`config/sendgrid_templates.yaml`** — initial empty registry file that CI/CD populates; read by `SendGridEmailDispatcher` (US-064) to look up template IDs at send time

The script is designed to be called as a CI/CD step on every deployment so that template content in source control is always authoritative.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Idempotent: create if not found, update if exists | Enables re-runs without duplication; existing template ID is re-used so `sendgrid_templates.yaml` remains stable across redeploys |
| Template ID lookup via `GET /v3/templates?generations=dynamic` | Matches by `name` field to find existing template before creating a new one |
| New version POSTed to existing template ID | SendGrid preserves version history; previous version is archived automatically (US-066 Scenario 3) |
| `SENDGRID_API_KEY` from env var (never hardcoded) | OWASP A02 (Cryptographic Failures) — secrets must never appear in source |
| `config/sendgrid_templates.yaml` committed to Git with placeholder values | File structure tracked in Git; actual IDs written at deploy time by the script |
| Exit code 1 on any template upload failure | CI/CD pipeline must fail hard if templates cannot be uploaded — a broken template causes silent notification failures |
| Script uses `sendgrid` Python SDK (already in notification-service dependencies) | DRY — same SDK used by dispatcher; no additional dependencies |

Design refs: US-066 DoD, US-066 AC Scenario 3, US-064 TASK-004 (SendGrid dispatcher reads `template_id`), OWASP A02.

---

## Acceptance Criteria Addressed

| US-066 AC | Requirement |
|---|---|
| **Scenario 2** | Script uploads all 6 templates; exit code 0 only if all succeed |
| **Scenario 3** | New version POSTed to existing template ID; previous version archived by SendGrid |
| **DoD** | `upload_sendgrid_templates.py` exists and runs successfully on deploy |
| **DoD** | `config/sendgrid_templates.yaml` updated with template IDs after upload |

---

## Implementation Steps

### 1. Create `config/sendgrid_templates.yaml` (initial placeholder)

```bash
mkdir -p config
```

```yaml
# config/sendgrid_templates.yaml
#
# SendGrid Dynamic Template ID registry.
# DO NOT edit manually — this file is updated automatically by
# notifications/upload_sendgrid_templates.py during CI/CD deployment.
#
# Template IDs are populated at deploy time. Placeholder values below
# are intentional; the script overwrites them on first deploy.
#
# Usage (notification dispatcher):
#   from app.config import sendgrid_templates
#   template_id = sendgrid_templates["patient_portal_link"]
#
# Refs: US-066 DoD, US-064 TASK-004

patient_portal_link: ""
appointment_reminder: ""
medication_reminder: ""
care_team_escalation: ""
ed_boarding_alert: ""
housekeeping_notification: ""
```

---

### 2. Create `notifications/upload_sendgrid_templates.py`

```python
#!/usr/bin/env python3
"""SendGrid Dynamic Template upload script — CI/CD deploy step.

Reads all 6 template JSON files from ``notifications/templates/``,
creates or updates each template via the SendGrid API v3, and writes
the resulting template IDs to ``config/sendgrid_templates.yaml``.

Usage (CI/CD step):
    SENDGRID_API_KEY=<secret> python notifications/upload_sendgrid_templates.py

Exit codes:
    0 — all 6 templates uploaded successfully; YAML registry updated.
    1 — one or more templates failed to upload; pipeline must abort.

Design refs:
    US-066 DoD, US-066 AC Scenario 3
    SendGrid API v3: POST /v3/templates, POST /v3/templates/{id}/versions
    OWASP A02: SENDGRID_API_KEY read from env var, never hardcoded.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from sendgrid import SendGridAPIClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).parent / "templates"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sendgrid_templates.yaml"

TEMPLATE_NAMES = [
    "patient_portal_link",
    "appointment_reminder",
    "medication_reminder",
    "care_team_escalation",
    "ed_boarding_alert",
    "housekeeping_notification",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Read SENDGRID_API_KEY from environment — never from source code."""
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logger.error(
            "SENDGRID_API_KEY environment variable is not set. "
            "Set it via GCP Secret Manager in the CI/CD pipeline."
        )
        sys.exit(1)
    return api_key


def _load_template_json(template_name: str) -> dict[str, Any]:
    """Load and validate template JSON from notifications/templates/."""
    path = TEMPLATES_DIR / f"{template_name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Template file not found: {path}. "
            "Ensure TASK-002 files are committed to notifications/templates/."
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _fetch_existing_templates(client: SendGridAPIClient) -> dict[str, str]:
    """Return mapping of template name → template ID for existing dynamic templates.

    Uses GET /v3/templates?generations=dynamic to list all existing templates
    and returns a dict keyed by template name for idempotent create/update logic.
    """
    response = client.client.templates.get(query_params={"generations": "dynamic"})
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch existing templates: HTTP {response.status_code} — {response.body}"
        )
    body = json.loads(response.body)
    return {t["name"]: t["id"] for t in body.get("result", [])}


def _create_template(client: SendGridAPIClient, name: str) -> str:
    """Create a new SendGrid Dynamic Template and return its ID."""
    payload = {"name": name, "generation": "dynamic"}
    response = client.client.templates.post(request_body=payload)
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to create template '{name}': HTTP {response.status_code} — {response.body}"
        )
    return json.loads(response.body)["id"]


def _upload_version(
    client: SendGridAPIClient,
    template_id: str,
    version_payload: dict[str, Any],
) -> None:
    """POST a new version to an existing template, archiving the previous version."""
    response = client.client.templates._(template_id).versions.post(
        request_body=version_payload
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to upload version for template ID '{template_id}': "
            f"HTTP {response.status_code} — {response.body}"
        )


def _upload_template(
    client: SendGridAPIClient,
    existing: dict[str, str],
    template_name: str,
) -> str:
    """Create or update a single SendGrid Dynamic Template.

    Strategy:
    - If template name already exists in SendGrid → POST a new version to its ID
      (previous version is automatically archived by SendGrid).
    - If template does not exist → create the template first, then POST first version.

    Returns the SendGrid template ID (stable across version updates).
    """
    template_data = _load_template_json(template_name)
    version_payload = template_data["versions"][0]

    if template_name in existing:
        template_id = existing[template_name]
        logger.info("Updating existing template '%s' (ID: %s).", template_name, template_id)
    else:
        template_id = _create_template(client, template_name)
        logger.info("Created new template '%s' (ID: %s).", template_name, template_id)

    _upload_version(client, template_id, version_payload)
    logger.info("Version uploaded for template '%s'.", template_name)
    return template_id


def _write_yaml_registry(template_ids: dict[str, str]) -> None:
    """Overwrite config/sendgrid_templates.yaml with the latest template IDs."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# config/sendgrid_templates.yaml\n"
        "#\n"
        "# SendGrid Dynamic Template ID registry.\n"
        "# AUTO-GENERATED by notifications/upload_sendgrid_templates.py — do not edit manually.\n"
        "# Refs: US-066 DoD, US-064 TASK-004\n"
        "#\n"
    )
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.dump(template_ids, fh, default_flow_style=False, sort_keys=True)

    logger.info("Template ID registry written to %s.", CONFIG_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Upload all 6 SendGrid Dynamic Templates and update the YAML registry."""
    api_key = _get_api_key()
    client = SendGridAPIClient(api_key=api_key)

    existing = _fetch_existing_templates(client)
    logger.info("Found %d existing SendGrid templates.", len(existing))

    template_ids: dict[str, str] = {}
    failed: list[str] = []

    for name in TEMPLATE_NAMES:
        try:
            template_ids[name] = _upload_template(client, existing, name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to upload template '%s': %s", name, exc)
            failed.append(name)

    if failed:
        logger.error(
            "Upload failed for %d template(s): %s. CI/CD pipeline aborting.",
            len(failed),
            ", ".join(failed),
        )
        sys.exit(1)

    _write_yaml_registry(template_ids)
    logger.info(
        "All %d SendGrid Dynamic Templates uploaded successfully.", len(TEMPLATE_NAMES)
    )


if __name__ == "__main__":
    main()
```

---

### 3. CI/CD integration (Cloud Build step)

Add to the notification-service Cloud Build config (`cloudbuild.yaml`):

```yaml
# Cloud Build step: upload SendGrid templates before deploying notification-service
- name: 'python:3.11-slim'
  id: upload-sendgrid-templates
  entrypoint: bash
  args:
    - '-c'
    - |
      pip install sendgrid pyyaml --quiet
      SENDGRID_API_KEY=$$(gcloud secrets versions access latest \
        --secret=sendgrid-api-key --project=$PROJECT_ID) \
      python notifications/upload_sendgrid_templates.py
  waitFor: ['-']  # Run as early step, no prerequisite
```

---

## Validation Checklist

- [ ] `config/sendgrid_templates.yaml` exists with 6 placeholder keys
- [ ] `upload_sendgrid_templates.py` reads `SENDGRID_API_KEY` from env var — no hardcoded key
- [ ] Script exits with code `1` if any template upload fails
- [ ] Script correctly handles the case where a template already exists (update path)
- [ ] Script correctly handles the case where a template is new (create path)
- [ ] `config/sendgrid_templates.yaml` is overwritten with actual IDs after successful run
- [ ] CI/CD Cloud Build step added and references GCP Secret Manager for `SENDGRID_API_KEY`

---

## Files Created

| File | Purpose |
|------|---------|
| `notifications/upload_sendgrid_templates.py` | CI/CD upload script |
| `config/sendgrid_templates.yaml` | Template ID registry (populated by script at deploy time) |

---

## Dependencies

| Dependency | Direction | Notes |
|---|---|---|
| TASK-001 | Upstream | `TEMPLATE_NAMES` list must match all 6 schema `template_name` values |
| TASK-002 | Upstream | Script reads JSON files from `notifications/templates/` |
| US-064 TASK-004 | Downstream | `SendGridEmailDispatcher` reads `config/sendgrid_templates.yaml` to resolve template IDs |
