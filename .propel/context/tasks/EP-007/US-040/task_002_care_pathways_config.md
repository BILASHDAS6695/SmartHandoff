---
id: TASK-002
title: "config/care_pathways.yaml — Risk Tier Pathway Configuration & Pydantic Config Model"
user_story: US-040
epic: EP-007
sprint: 2
layer: Configuration
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-040/TASK-001]
---

# TASK-002: config/care_pathways.yaml — Risk Tier Pathway Configuration & Pydantic Config Model

> **Story:** US-040 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Configuration | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-040 DoD explicitly requires: *"Risk tier-to-pathway mapping in `config/care_pathways.yaml` (configurable follow-up days)"*. Externalising the mapping allows clinical administrators to adjust follow-up windows without code changes or redeployment (configuration reloaded at service startup).

This task creates:
1. `backend/config/care_pathways.yaml` — the single source of truth for all risk tier pathway parameters (follow-up days, appointment type, care manager alert flag)
2. `backend/app/config/care_pathways.py` — a Pydantic `CarePathwayConfig` model that parses and validates the YAML at application startup, loaded into `app.state.care_pathways`

**Design references:**
- US-040 DoD — `config/care_pathways.yaml` with configurable follow-up days
- US-040 AC Scenario 2 — HIGH: `required_followup_days=7`; `appointment_type=HIGH_RISK_FOLLOW_UP`; alert dispatched
- US-040 AC Scenario 3 — MEDIUM: `14 days`; `appointment_type=STANDARD_FOLLOW_UP`; no alert
- US-040 AC Scenario 4 — LOW: `30 days`; `appointment_type=ROUTINE_FOLLOW_UP`; no alert
- design.md §10.3 — Secret Manager referenced config; no hardcoded credentials

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `HIGH` pathway: `followup_days=7`, `appointment_type=HIGH_RISK_FOLLOW_UP`, `alert_care_manager=true` |
| Scenario 3 | `MEDIUM` pathway: `followup_days=14`, `appointment_type=STANDARD_FOLLOW_UP`, `alert_care_manager=false` |
| Scenario 4 | `LOW` pathway: `followup_days=30`, `appointment_type=ROUTINE_FOLLOW_UP`, `alert_care_manager=false` |

---

## Implementation Steps

### 1. Create directory and files

```bash
mkdir -p backend/config
touch backend/config/care_pathways.yaml
mkdir -p backend/app/config
touch backend/app/config/__init__.py
touch backend/app/config/care_pathways.py
```

### 2. Create `backend/config/care_pathways.yaml`

```yaml
# SmartHandoff Follow-up Care Pathway Configuration
# Defines risk tier-to-pathway mapping for the FollowUpCareAgent.
#
# US-040 DoD: "Risk tier-to-pathway mapping in config/care_pathways.yaml (configurable follow-up days)"
#
# Fields per tier:
#   followup_days     : Calendar days from discharge_date for target_date calculation
#   appointment_type  : AppointmentType enum value persisted to the appointment table
#   alert_care_manager: Whether a CARE_MANAGER_ALERT is published to notification-requests Pub/Sub
#   required_followup_days: Days value included in the CARE_MANAGER_ALERT payload (HIGH tier only)
#
# To adjust follow-up windows, update this file and redeploy the followup-agent service.
# No code changes are required for window adjustments.

care_pathways:
  HIGH:
    followup_days: 7
    appointment_type: HIGH_RISK_FOLLOW_UP
    alert_care_manager: true
    required_followup_days: 7

  MEDIUM:
    followup_days: 14
    appointment_type: STANDARD_FOLLOW_UP
    alert_care_manager: false
    required_followup_days: null

  LOW:
    followup_days: 30
    appointment_type: ROUTINE_FOLLOW_UP
    alert_care_manager: false
    required_followup_days: null
```

### 3. Implement `backend/app/config/care_pathways.py`

```python
"""Pydantic configuration model for risk tier care pathways.

Parses and validates `backend/config/care_pathways.yaml` at application startup.
Loaded into `app.state.care_pathways` by the FollowUpCareAgent FastAPI lifespan.

Usage:
    from app.config.care_pathways import load_care_pathways, CarePathwayConfig

    pathways = load_care_pathways()
    high_pathway = pathways["HIGH"]
    # high_pathway.followup_days == 7
    # high_pathway.alert_care_manager == True

Design refs:
    US-040 DoD — config/care_pathways.yaml with configurable follow-up days
    US-040 AC Scenarios 2, 3, 4 — tier-specific followup_days, appointment_type, alert flag
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Resolved at import time — works for both local dev and Cloud Run container
_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "care_pathways.yaml"


class TierPathwayConfig(BaseModel):
    """Configuration for a single risk tier pathway.

    Attributes:
        followup_days:         Calendar days from discharge_date to set appointment target_date.
        appointment_type:      AppointmentType enum value for the created appointment record.
        alert_care_manager:    Whether to publish a CARE_MANAGER_ALERT to notification-requests.
        required_followup_days: Days value embedded in the CARE_MANAGER_ALERT payload (HIGH only).
    """

    followup_days: int = Field(..., gt=0, description="Calendar days from discharge for follow-up")
    appointment_type: str = Field(..., description="AppointmentType enum value")
    alert_care_manager: bool = Field(..., description="Whether to publish CARE_MANAGER_ALERT")
    required_followup_days: int | None = Field(
        None,
        description="Days value in alert payload; None for non-alert tiers",
    )


CarePathwayConfig = dict[str, TierPathwayConfig]


def load_care_pathways(config_path: Path = _CONFIG_PATH) -> CarePathwayConfig:
    """Load and validate care pathway configuration from YAML.

    Args:
        config_path: Absolute path to care_pathways.yaml (defaults to bundled config).

    Returns:
        Dict mapping risk tier string (HIGH/MEDIUM/LOW) to TierPathwayConfig.

    Raises:
        FileNotFoundError: If care_pathways.yaml does not exist at config_path.
        pydantic.ValidationError: If the YAML structure does not match TierPathwayConfig.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Care pathway config not found: {config_path}")

    with config_path.open() as f:
        raw = yaml.safe_load(f)

    pathways: CarePathwayConfig = {
        tier: TierPathwayConfig(**values)
        for tier, values in raw["care_pathways"].items()
    }

    logger.info(
        "Care pathway config loaded",
        extra={"tiers": list(pathways.keys()), "config_path": str(config_path)},
    )
    return pathways
```

### 4. Verify Pydantic model parses correctly (quick sanity check)

```bash
cd backend
python -c "
from app.config.care_pathways import load_care_pathways
p = load_care_pathways()
assert p['HIGH'].followup_days == 7
assert p['HIGH'].alert_care_manager is True
assert p['HIGH'].required_followup_days == 7
assert p['MEDIUM'].followup_days == 14
assert p['MEDIUM'].alert_care_manager is False
assert p['LOW'].followup_days == 30
assert p['LOW'].alert_care_manager is False
print('care_pathways.yaml: all assertions passed')
"
```

---

## Validation Checklist

- [ ] `backend/config/care_pathways.yaml` created with `HIGH`, `MEDIUM`, `LOW` tier entries
- [ ] `HIGH` tier: `followup_days=7`, `appointment_type=HIGH_RISK_FOLLOW_UP`, `alert_care_manager=true`, `required_followup_days=7`
- [ ] `MEDIUM` tier: `followup_days=14`, `appointment_type=STANDARD_FOLLOW_UP`, `alert_care_manager=false`
- [ ] `LOW` tier: `followup_days=30`, `appointment_type=ROUTINE_FOLLOW_UP`, `alert_care_manager=false`
- [ ] `TierPathwayConfig` Pydantic model validates all required fields with correct types
- [ ] `load_care_pathways()` raises `FileNotFoundError` when config file is missing (tested in unit tests TASK-005)
- [ ] Sanity check script exits cleanly

---

## DoD Exit Criteria

- [ ] `backend/config/care_pathways.yaml` created with all 3 tier entries
- [ ] `backend/app/config/care_pathways.py` implemented with `TierPathwayConfig`, `CarePathwayConfig`, `load_care_pathways()`
- [ ] Pydantic validation passes for all three tier entries
- [ ] File is co-located with application config (not hardcoded in agent logic)
