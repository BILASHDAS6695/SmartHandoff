---
id: TASK-001
title: "Create SLA Configuration YAML and `SLAConfig` Loader for Per-Agent Thresholds"
user_story: US-021
epic: EP-003
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-006/TASK-005]
---

# TASK-001: Create SLA Configuration YAML and `SLAConfig` Loader for Per-Agent Thresholds

> **Story:** US-021 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-021 Scenario 4 and DoD explicitly forbid hardcoding SLA thresholds:

> *"SLA thresholds stored as application config (YAML or DB config table) — not hardcoded"*

This task establishes a single-source-of-truth `sla_config.yaml` file alongside a `SLAConfig` Pydantic dataclass that loads, validates, and exposes per-agent thresholds to the `SLAMonitor` (TASK-003) and the API endpoint (TASK-005).

Per-agent thresholds from US-021 Technical Notes:

| Agent Type | SLA (minutes) |
|---|---|
| `DOCUMENTATION` | 30 |
| `MEDICATION_RECONCILIATION` | 60 |
| `BED_MANAGEMENT` | 15 |
| `FOLLOW_UP_CARE` | 120 |
| `PATIENT_COMMUNICATION` | 30 |

The `SLAConfig` loader is the single place where these values live. The `SLAMonitor` imports the loader — no other module defines thresholds.

---

## Acceptance Criteria Addressed

| US-021 AC | Requirement |
|---|---|
| **Scenario 4** | `BED_MANAGEMENT` agent has 15-minute SLA and `DOCUMENTATION` has 30 minutes — monitor applies correct threshold per agent type |
| **DoD** | SLA thresholds stored as application config — not hardcoded |

---

## Implementation Steps

### 1. Scaffold the `sla-monitor` service structure

This task creates the foundation for the SLA monitoring service:

```
sla-monitor/
├── app/
│   ├── __init__.py
│   ├── main.py                        ← entry point (TASK-003)
│   ├── config/
│   │   ├── __init__.py
│   │   ├── sla_config.yaml            ← THIS TASK
│   │   └── sla_loader.py              ← THIS TASK
│   ├── monitor/
│   │   ├── __init__.py
│   │   └── sla_monitor.py             ← TASK-003
│   ├── publisher/
│   │   ├── __init__.py
│   │   └── escalation_publisher.py    ← TASK-004
│   └── models/
│       └── agent_task.py              ← imported from shared lib (US-006)
├── Dockerfile
├── requirements.txt
└── tests/
    └── unit/
        ├── test_sla_loader.py         ← THIS TASK
        └── test_sla_monitor.py        ← TASK-006
```

```bash
mkdir -p sla-monitor/app/config sla-monitor/app/monitor sla-monitor/app/publisher sla-monitor/app/models
mkdir -p sla-monitor/tests/unit
touch sla-monitor/app/__init__.py
touch sla-monitor/app/config/__init__.py
touch sla-monitor/app/monitor/__init__.py
touch sla-monitor/app/publisher/__init__.py
```

### 2. Create `sla-monitor/app/config/sla_config.yaml`

```yaml
# SLA thresholds (minutes) per agent type.
# Source of truth — do NOT duplicate these values in Python code.
# Referenced by: SLAMonitor (app/monitor/sla_monitor.py)
# US-021 Technical Notes: {DOCUMENTATION: 30, MEDICATION_RECONCILIATION: 60,
#                           BED_MANAGEMENT: 15, FOLLOW_UP_CARE: 120,
#                           PATIENT_COMMUNICATION: 30}
sla_thresholds:
  DOCUMENTATION: 30
  MEDICATION_RECONCILIATION: 60
  BED_MANAGEMENT: 15
  FOLLOW_UP_CARE: 120
  PATIENT_COMMUNICATION: 30

# Polling interval for the SLA monitor background job (seconds).
# 5 minutes = 300 seconds (US-021 DoD).
monitor_interval_seconds: 300

# Escalation idempotency window (minutes).
# Only one escalation fires per (encounter_id, agent_type) within this window.
# Prevents alert fatigue per US-021 Technical Notes.
escalation_dedup_window_minutes: 30
```

### 3. Create `sla-monitor/app/config/sla_loader.py`

```python
"""SLA configuration loader — single source of truth for per-agent SLA thresholds.

Loads `sla_config.yaml` from the directory containing this module.
Provides a validated `SLAConfig` dataclass accessible to the SLAMonitor
and task status API endpoint.

US-021 DoD: SLA thresholds stored as application config — not hardcoded.
US-021 Scenario 4: Per-agent SLA threshold applied correctly by monitor.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "sla_config.yaml"

# All agent types defined in the system. Loader validates that the YAML
# provides a threshold for every agent type before the monitor starts.
KNOWN_AGENT_TYPES: frozenset[str] = frozenset(
    {
        "DOCUMENTATION",
        "MEDICATION_RECONCILIATION",
        "BED_MANAGEMENT",
        "FOLLOW_UP_CARE",
        "PATIENT_COMMUNICATION",
    }
)


class SLAConfig(BaseModel):
    """Validated SLA configuration loaded from sla_config.yaml.

    Attributes:
        sla_thresholds: Mapping of agent_type → SLA minutes.
        monitor_interval_seconds: Background job polling interval.
        escalation_dedup_window_minutes: Idempotency window for escalations.
    """

    sla_thresholds: dict[str, int] = Field(
        ...,
        description="Per-agent SLA thresholds in minutes.",
    )
    monitor_interval_seconds: int = Field(
        default=300,
        ge=60,
        description="SLA monitor polling interval in seconds.",
    )
    escalation_dedup_window_minutes: int = Field(
        default=30,
        ge=1,
        description="Idempotency window to suppress duplicate escalations.",
    )

    @field_validator("sla_thresholds")
    @classmethod
    def _all_thresholds_positive(cls, v: dict[str, int]) -> dict[str, int]:
        """Reject any threshold ≤ 0."""
        for agent_type, minutes in v.items():
            if minutes <= 0:
                raise ValueError(
                    f"SLA threshold for {agent_type!r} must be > 0, got {minutes}"
                )
        return v

    @model_validator(mode="after")
    def _all_agent_types_covered(self) -> "SLAConfig":
        """Fail-fast if the YAML is missing a threshold for any known agent type."""
        missing = KNOWN_AGENT_TYPES - set(self.sla_thresholds.keys())
        if missing:
            raise ValueError(
                f"sla_config.yaml is missing thresholds for agent types: {sorted(missing)}"
            )
        return self

    def threshold_for(self, agent_type: str) -> int:
        """Return SLA threshold (minutes) for the given agent type.

        Falls back to a conservative 30-minute default for unknown agent types
        introduced after the YAML was last updated, and logs a warning.
        """
        if agent_type not in self.sla_thresholds:
            logger.warning(
                "No SLA threshold configured for agent_type=%r; defaulting to 30 minutes",
                agent_type,
            )
            return 30
        return self.sla_thresholds[agent_type]


@lru_cache(maxsize=1)
def load_sla_config(config_path: Path = _CONFIG_PATH) -> SLAConfig:
    """Load and validate SLA configuration from YAML.

    Cached after first call — the YAML file is read once at startup.
    Tests can bypass the cache by calling `load_sla_config.cache_clear()`.

    Args:
        config_path: Path to the YAML config file. Defaults to the bundled
                     ``sla_config.yaml`` next to this module.

    Returns:
        Validated :class:`SLAConfig` instance.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If required agent types are missing or values are invalid.
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"SLA configuration file not found: {config_path}. "
            "Ensure sla_config.yaml is present in app/config/."
        )

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    config = SLAConfig(**raw)
    logger.info(
        "SLA configuration loaded: %d agent types, monitor_interval=%ds",
        len(config.sla_thresholds),
        config.monitor_interval_seconds,
    )
    return config
```

### 4. Create `sla-monitor/tests/unit/test_sla_loader.py`

```python
"""Unit tests for SLA configuration loader.

US-021 DoD: Config loading validated.
US-021 Scenario 4: Per-agent thresholds correctly parsed and accessible.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.config.sla_loader import SLAConfig, load_sla_config


@pytest.fixture
def valid_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        sla_thresholds:
          DOCUMENTATION: 30
          MEDICATION_RECONCILIATION: 60
          BED_MANAGEMENT: 15
          FOLLOW_UP_CARE: 120
          PATIENT_COMMUNICATION: 30
        monitor_interval_seconds: 300
        escalation_dedup_window_minutes: 30
    """)
    p = tmp_path / "sla_config.yaml"
    p.write_text(content)
    return p


def test_load_returns_sla_config(valid_yaml: Path) -> None:
    load_sla_config.cache_clear()
    config = load_sla_config(valid_yaml)
    assert isinstance(config, SLAConfig)


def test_bed_management_threshold_is_15(valid_yaml: Path) -> None:
    """US-021 Scenario 4: BED_MANAGEMENT SLA = 15 minutes."""
    load_sla_config.cache_clear()
    config = load_sla_config(valid_yaml)
    assert config.threshold_for("BED_MANAGEMENT") == 15


def test_documentation_threshold_is_30(valid_yaml: Path) -> None:
    """US-021 Scenario 4: DOCUMENTATION SLA = 30 minutes."""
    load_sla_config.cache_clear()
    config = load_sla_config(valid_yaml)
    assert config.threshold_for("DOCUMENTATION") == 30


def test_missing_agent_type_raises(tmp_path: Path) -> None:
    """Fail-fast if a known agent type is absent from the YAML."""
    content = textwrap.dedent("""\
        sla_thresholds:
          DOCUMENTATION: 30
        monitor_interval_seconds: 300
        escalation_dedup_window_minutes: 30
    """)
    p = tmp_path / "sla_config.yaml"
    p.write_text(content)
    load_sla_config.cache_clear()
    with pytest.raises(ValueError, match="missing thresholds"):
        load_sla_config(p)


def test_zero_threshold_raises(tmp_path: Path) -> None:
    content = textwrap.dedent("""\
        sla_thresholds:
          DOCUMENTATION: 0
          MEDICATION_RECONCILIATION: 60
          BED_MANAGEMENT: 15
          FOLLOW_UP_CARE: 120
          PATIENT_COMMUNICATION: 30
        monitor_interval_seconds: 300
        escalation_dedup_window_minutes: 30
    """)
    p = tmp_path / "sla_config.yaml"
    p.write_text(content)
    load_sla_config.cache_clear()
    with pytest.raises(ValueError, match="must be > 0"):
        load_sla_config(p)


def test_missing_file_raises(tmp_path: Path) -> None:
    load_sla_config.cache_clear()
    with pytest.raises(FileNotFoundError):
        load_sla_config(tmp_path / "nonexistent.yaml")
```

---

## Validation Checklist

- [ ] `sla_config.yaml` present in `sla-monitor/app/config/`
- [ ] `SLAConfig.threshold_for("BED_MANAGEMENT")` returns `15`
- [ ] `SLAConfig.threshold_for("DOCUMENTATION")` returns `30`
- [ ] `load_sla_config()` raises `ValueError` if any `KNOWN_AGENT_TYPES` entry is absent from YAML
- [ ] `load_sla_config()` raises `FileNotFoundError` when YAML file is missing
- [ ] `lru_cache` prevents re-reading YAML on every monitor tick
- [ ] All 6 unit tests pass: `pytest sla-monitor/tests/unit/test_sla_loader.py -v`

---

## Files Created

| Path | Purpose |
|---|---|
| `sla-monitor/app/config/sla_config.yaml` | Per-agent SLA thresholds (single source of truth) |
| `sla-monitor/app/config/sla_loader.py` | Pydantic-validated config loader with `lru_cache` |
| `sla-monitor/tests/unit/test_sla_loader.py` | 6 unit tests for config loading and validation |

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `pydantic>=2.0` | Runtime | Model validation |
| `pyyaml` | Runtime | YAML parsing |
| `pytest` | Test | Unit test framework |
