---
id: TASK-001
title: "Config Files & Pydantic Schemas — UrgencyKeywordConfig, EmergencyContactConfig, UrgencyDetectionResult"
user_story: US-044
epic: EP-008
sprint: 2
layer: Backend / Configuration
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-044]
---

# TASK-001: Config Files & Pydantic Schemas — UrgencyKeywordConfig, EmergencyContactConfig, UrgencyDetectionResult

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / Configuration | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-044 requires two YAML configuration files and a set of Pydantic schemas that are consumed by every subsequent task in the story. The keyword list and emergency contacts must be externally configurable (no hardcoding inside detector logic) so hospital administrators can update them without code changes.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `config/urgency_keywords.yaml` | YAML | Ordered list of urgency phrases used for Phase 1 keyword matching |
| `config/emergency_contacts.yaml` | YAML | Hospital-specific emergency contact numbers and display text |
| `UrgencyDetectionResult` | Pydantic schema | Result produced by the `UrgencyDetector` (both phases) |
| `GeminiUrgencyClassification` | Pydantic schema | Structured output schema for Gemini semantic classification call |
| `UrgencyAlertPayload` | Pydantic schema | Payload published to `notification-requests` Pub/Sub topic |
| `EmergencyContactConfig` | Pydantic schema | Typed representation of `config/emergency_contacts.yaml` |

**Design references:**
- design.md §3.1 — Patient Communication Agent: chatbot, urgency detection, escalation routing
- design.md §7.3 AIR-020 — Vertex AI structured output validated with Pydantic schemas
- design.md §7.5 AIR-040 — Notification Service reads from `notification-requests` Pub/Sub topic
- US-044 AC Scenario 2 — keyword list configurable in `config/urgency_keywords.yaml`
- US-044 AC Scenario 3 — Gemini structured output `{urgency: bool, confidence: float}` with threshold 0.8
- US-044 Technical Notes — urgency alert payload: `{encounter_id, patient_first_name (only), urgency_message_summary, timestamp}` — minimum PHI

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `config/urgency_keywords.yaml` defines all required phrases; loaded via `UrgencyKeywordConfig` |
| Scenario 3 | `GeminiUrgencyClassification` schema enforces `{urgency: bool, confidence: float}` structured output |
| All | `UrgencyDetectionResult` carries the combined verdict consumed by TASK-002, TASK-003, and TASK-004 |

---

## Implementation Steps

### 1. Create module and config directory structure

```bash
mkdir -p backend/app/agents/patient_comm/urgency
touch backend/app/agents/patient_comm/urgency/__init__.py
touch backend/app/agents/patient_comm/urgency/schemas.py
touch backend/app/agents/patient_comm/urgency/config_loader.py

mkdir -p config
touch config/urgency_keywords.yaml
touch config/emergency_contacts.yaml
```

### 2. Create `config/urgency_keywords.yaml`

```yaml
# Urgency keyword/phrase list for US-044 Phase 1 detection.
# All phrases are matched case-insensitively.
# Add or remove phrases without code changes — update and redeploy config only.
#
# Design ref: US-044 AC Scenario 2
keywords:
  - "chest pain"
  - "can't breathe"
  - "cannot breathe"
  - "severe bleeding"
  - "unconscious"
  - "not breathing"
  - "stroke"
  - "suicide"
  - "heart attack"
  - "seizure"
  - "anaphylaxis"
  - "allergic reaction"
  - "unresponsive"
  - "collapsed"
  - "overdose"
```

### 3. Create `config/emergency_contacts.yaml`

```yaml
# Hospital-specific emergency contact configuration for US-044.
# Displayed immediately in the chat UI when urgency is detected.
# Contains no PHI — these are institutional contacts only.
#
# Design ref: US-044 Technical Notes
emergency:
  primary_number: "911"
  hospital_number: "1-800-HOSPITAL"
  display_message: >
    ⚠ Emergency Alert: This sounds serious. Call 911 immediately or go to the
    nearest emergency room. Your care team has been notified.
  care_team_alert_channel: "notification-requests"
```

### 4. Implement `backend/app/agents/patient_comm/urgency/schemas.py`

```python
"""Pydantic schemas and domain models for the Urgency Detector (US-044).

All schemas are consumed by:
    - task_002: UrgencyDetector Phase 1 (keyword matching)
    - task_003: UrgencyDetector Phase 2 (Gemini semantic classification)
    - task_004: EmergencyAlertHandler (Pub/Sub publish, DB write)
    - task_005: POST /api/v1/chat pipeline integration

Design refs:
    US-044 AC Scenarios 1–4
    design.md §7.3 AIR-020 — Vertex AI structured output with Pydantic validation
    design.md §7.5 AIR-040 — notification-requests Pub/Sub payload contract
    US-044 Technical Notes — minimum-PHI alert payload
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Detection phase enumeration
# ---------------------------------------------------------------------------

class DetectionPhase(str, Enum):
    """Which detection phase triggered the urgency verdict.

    KEYWORD  — Phase 1 regex match (O(n), <10ms) — US-044 Technical Notes
    SEMANTIC — Phase 2 Gemini Flash classification (~500ms) — US-044 Technical Notes
    NONE     — No urgency detected; message proceeds to normal chatbot pipeline
    """

    KEYWORD = "KEYWORD"
    SEMANTIC = "SEMANTIC"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Gemini structured output schema — Phase 2 classification
# ---------------------------------------------------------------------------

class GeminiUrgencyClassification(BaseModel):
    """Structured JSON output from Gemini Flash urgency classification.

    Gemini is prompted to return ONLY this schema in JSON mode:
        response_mime_type="application/json"

    The `confidence` field maps to the 0.8 threshold defined in US-044 DoD:
        if classification.urgency and classification.confidence >= 0.8 → trigger urgency response
    """

    urgency: bool = Field(
        ...,
        description="True if the message contains a medical urgency signal",
    )
    confidence: Annotated[
        float,
        Field(
            ge=0.0,
            le=1.0,
            description="Confidence score; urgency triggered only when ≥ 0.8",
        ),
    ]


# ---------------------------------------------------------------------------
# Combined detection result
# ---------------------------------------------------------------------------

class UrgencyDetectionResult(BaseModel):
    """Result produced by UrgencyDetector after running both phases.

    Consumed by task_004 (EmergencyAlertHandler) and task_005 (pipeline integration).

    If `is_urgent` is False, `detection_phase` is `NONE` and `matched_phrase`
    is None — the message proceeds to the normal US-043 chatbot pipeline.
    """

    is_urgent: bool = Field(
        ...,
        description="True if urgency was detected by either Phase 1 or Phase 2",
    )
    detection_phase: DetectionPhase = Field(
        ...,
        description="Which phase triggered the verdict",
    )
    matched_phrase: str | None = Field(
        default=None,
        description="The keyword phrase that matched in Phase 1; None for semantic or non-urgent",
    )
    confidence: float | None = Field(
        default=None,
        description="Gemini confidence score (Phase 2 only); None for keyword or non-urgent",
    )
    message_summary: str | None = Field(
        default=None,
        description=(
            "Brief non-PHI summary of the urgency trigger for the alert payload. "
            "Maximum 100 characters. Never contains patient name, DOB, or MRN."
        ),
        max_length=100,
    )


# ---------------------------------------------------------------------------
# Emergency contact configuration schema
# ---------------------------------------------------------------------------

class EmergencyContactConfig(BaseModel):
    """Typed representation of config/emergency_contacts.yaml.

    Loaded once at agent startup from the YAML file and injected into
    EmergencyAlertHandler. Never serialised to logs or responses.
    """

    primary_number: str = Field(..., description="Primary emergency number, e.g. '911'")
    hospital_number: str = Field(..., description="Hospital direct emergency line")
    display_message: str = Field(
        ...,
        description="Full message displayed to patient in chat UI when urgency detected",
    )
    care_team_alert_channel: str = Field(
        ...,
        description="Pub/Sub topic name for CARE_TEAM_URGENCY_ALERT messages",
    )


# ---------------------------------------------------------------------------
# Urgency alert Pub/Sub payload — minimum PHI
# ---------------------------------------------------------------------------

class UrgencyAlertPayload(BaseModel):
    """Payload published to the `notification-requests` Pub/Sub topic.

    HIPAA / US-044 Technical Notes:
        Only `patient_first_name` (not full name, not MRN, not DOB) is included.
        `urgency_message_summary` is a system-generated phrase, NOT the raw patient message.
        The raw patient message MUST NOT appear in this payload.

    Design ref: design.md §7.5 AIR-040 — idempotency key prevents duplicate sends.
    """

    event_type: str = Field(
        default="CARE_TEAM_URGENCY_ALERT",
        description="Fixed event type consumed by the Notification Service",
    )
    encounter_id: str = Field(..., description="UUID of the patient's encounter")
    patient_first_name: str = Field(
        ...,
        description="Patient's first name only — minimum PHI for care team alert",
    )
    urgency_message_summary: str = Field(
        ...,
        description="System-generated non-PHI phrase describing the urgency trigger",
        max_length=100,
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of urgency detection",
    )
    channel: str = Field(
        default="sms",
        description="Notification channel; 'sms' triggers Twilio dispatch in Notification Service",
    )
```

### 5. Implement `backend/app/agents/patient_comm/urgency/config_loader.py`

```python
"""Loader for urgency_keywords.yaml and emergency_contacts.yaml (US-044).

Loads configs once at module import and caches in module-level variables.
Config is loaded from the path specified by the URGENCY_CONFIG_DIR env var
(defaults to `config/` relative to the project root).

Design ref: US-044 DoD — keyword list in config/urgency_keywords.yaml (configurable).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

from backend.app.agents.patient_comm.urgency.schemas import EmergencyContactConfig

_CONFIG_DIR = Path(os.environ.get("URGENCY_CONFIG_DIR", "config"))


@lru_cache(maxsize=1)
def load_urgency_keywords() -> list[re.Pattern[str]]:
    """Return compiled case-insensitive regex patterns for each urgency keyword.

    Patterns are compiled once and cached. The word-boundary anchors (\\b) ensure
    "chest pain" does not match "chestpain123" but does match "I have chest pain!".
    """
    path = _CONFIG_DIR / "urgency_keywords.yaml"
    raw: dict = yaml.safe_load(path.read_text())
    phrases: list[str] = raw.get("keywords", [])
    return [re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE) for phrase in phrases]


@lru_cache(maxsize=1)
def load_emergency_contact_config() -> EmergencyContactConfig:
    """Return the parsed EmergencyContactConfig from emergency_contacts.yaml."""
    path = _CONFIG_DIR / "emergency_contacts.yaml"
    raw: dict = yaml.safe_load(path.read_text())
    return EmergencyContactConfig(**raw["emergency"])
```

---

## Validation Checklist

```bash
# Syntax check
python -c "
import ast, pathlib
for f in [
    'backend/app/agents/patient_comm/urgency/schemas.py',
    'backend/app/agents/patient_comm/urgency/config_loader.py',
]:
    ast.parse(pathlib.Path(f).read_text())
    print(f'{f} — syntax OK')
"

# YAML is valid
python -c "
import yaml, pathlib
for f in ['config/urgency_keywords.yaml', 'config/emergency_contacts.yaml']:
    yaml.safe_load(pathlib.Path(f).read_text())
    print(f'{f} — YAML valid')
"

# Schema import and basic assertions
python -c "
from backend.app.agents.patient_comm.urgency.schemas import (
    GeminiUrgencyClassification, UrgencyDetectionResult,
    UrgencyAlertPayload, EmergencyContactConfig, DetectionPhase,
)
# GeminiUrgencyClassification rejects confidence > 1.0
from pydantic import ValidationError
try:
    GeminiUrgencyClassification(urgency=True, confidence=1.5)
    raise AssertionError('Should have raised')
except ValidationError:
    print('Confidence > 1.0 rejected ✓')

# UrgencyAlertPayload message_summary max_length enforced
try:
    from backend.app.agents.patient_comm.urgency.schemas import UrgencyAlertPayload
    UrgencyAlertPayload(
        encounter_id='test-uuid',
        patient_first_name='Jane',
        urgency_message_summary='x' * 101,  # > 100 chars
    )
    raise AssertionError('Should have raised')
except ValidationError:
    print('message_summary max_length=100 enforced ✓')
print('All schema assertions passed ✓')
"

# Config loader compiles regex patterns
python -c "
from backend.app.agents.patient_comm.urgency.config_loader import (
    load_urgency_keywords, load_emergency_contact_config,
)
patterns = load_urgency_keywords()
assert len(patterns) >= 10, 'At least 10 urgency patterns expected'
config = load_emergency_contact_config()
assert '911' in config.primary_number
print(f'Loaded {len(patterns)} keyword patterns ✓')
print(f'Emergency contact config loaded — primary: {config.primary_number} ✓')
"
```

---

## Definition of Done

- [ ] `config/urgency_keywords.yaml` created with all AC Scenario 2 keywords (chest pain, can't breathe, severe bleeding, unconscious, stroke, suicide) plus additional clinical urgency phrases
- [ ] `config/emergency_contacts.yaml` created with hospital number, primary number, display message, and Pub/Sub channel
- [ ] `backend/app/agents/patient_comm/urgency/schemas.py` created with all five schemas
- [ ] `GeminiUrgencyClassification.confidence` field enforces `ge=0.0, le=1.0` range
- [ ] `UrgencyAlertPayload` contains no raw patient message content — only `patient_first_name` and `urgency_message_summary`
- [ ] `config_loader.py` uses `lru_cache` and compiles keyword patterns at startup
- [ ] Syntax check passes for all Python files
- [ ] YAML validation passes for both config files
- [ ] Schema assertion script passes without errors
