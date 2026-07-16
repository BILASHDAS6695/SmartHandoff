---
id: TASK-026-001
title: "Create `document_completeness.yaml` Config and `CompletenessConfig` Loader"
user_story: US-026
epic: EP-004
sprint: 2
layer: Backend — Configuration
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-025]
---

# TASK-026-001: Create `document_completeness.yaml` Config and `CompletenessConfig` Loader

> **Story:** US-026 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Configuration | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-026 Scenario 3 mandates that the required-fields list is configurable — adding a new field must not require a code change. This task establishes the YAML configuration file and the Python loader that reads it at startup. All downstream components (`CompletenessValidator`, TASK-026-002) import `CompletenessConfig` as their single source of truth.

The config is loaded once at import time and cached to avoid repeated disk I/O on every validation call (TR-001).

---

## Acceptance Criteria Addressed

| US-026 AC | Requirement |
|---|---|
| **Scenario 3** | Required fields defined in YAML config; adding a new field takes effect immediately without code changes |

---

## Implementation Steps

### 1. Create `config/document_completeness.yaml`

```yaml
# Document completeness configuration
# Controls which fields must be non-null and non-empty for each document type.
# Adding a field here immediately affects all future validation runs (US-026 AC Scenario 3).

document_types:
  discharge_summary:
    required_fields:
      - diagnosis_summary
      - medications_at_discharge
      - follow_up_instructions
      - warning_signs
      - activity_restrictions
```

### 2. Create `backend/config/completeness_config.py`

```python
"""
CompletenessConfig — YAML-backed configuration loader for document completeness rules.

Reads `config/document_completeness.yaml` once at import time. The config determines
which fields are mandatory per document type. Adding a field to the YAML file takes
effect on the next process restart — no code changes required (US-026 Scenario 3).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "document_completeness.yaml"


class CompletenessConfig:
    """
    Loader and accessor for document completeness field rules.

    Args:
        config_path: Absolute path to the YAML config file.
                     Defaults to `config/document_completeness.yaml` relative to project root.

    Raises:
        FileNotFoundError: If the YAML file does not exist at the resolved path.
        KeyError: If the YAML structure is missing the `document_types` root key.
    """

    def __init__(self, config_path: Path = _DEFAULT_CONFIG_PATH) -> None:
        self._config_path = config_path
        self._rules: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        """Parse the YAML file and populate the internal rules map."""
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Completeness config not found: {self._config_path}. "
                "Ensure config/document_completeness.yaml is present."
            )
        with self._config_path.open("r", encoding="utf-8") as fh:
            raw: dict = yaml.safe_load(fh)

        document_types: dict = raw.get("document_types", {})
        for doc_type, spec in document_types.items():
            fields: List[str] = spec.get("required_fields", [])
            self._rules[doc_type] = fields
            logger.info(
                "CompletenessConfig loaded: doc_type=%s required_fields=%s",
                doc_type,
                fields,
            )

    def get_required_fields(self, document_type: str) -> List[str]:
        """
        Return the list of required field names for the given document type.

        Args:
            document_type: Normalised document type key (e.g. 'discharge_summary').

        Returns:
            Ordered list of field name strings. Returns an empty list if the
            document type has no configured rules (non-blocking — validator will
            treat all documents of unknown types as COMPLETE).
        """
        return self._rules.get(document_type, [])

    @property
    def configured_document_types(self) -> List[str]:
        """Return all document types that have completeness rules configured."""
        return list(self._rules.keys())


@lru_cache(maxsize=1)
def get_completeness_config() -> CompletenessConfig:
    """
    Return a module-level cached singleton of CompletenessConfig.

    The cache is invalidated only on process restart. This is intentional —
    config changes require a deployment, which triggers a Cloud Run container
    restart.
    """
    config_path_override = os.getenv("COMPLETENESS_CONFIG_PATH")
    if config_path_override:
        return CompletenessConfig(config_path=Path(config_path_override))
    return CompletenessConfig()
```

### 3. Export from `backend/config/__init__.py`

```python
from config.completeness_config import CompletenessConfig, get_completeness_config

__all__ = ["CompletenessConfig", "get_completeness_config"]
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `config/document_completeness.yaml` |
| **Create** | `backend/config/completeness_config.py` |
| **Create/Update** | `backend/config/__init__.py` |

---

## Definition of Done

- [ ] `config/document_completeness.yaml` contains the five required fields for `discharge_summary`
- [ ] `CompletenessConfig._load()` parses the YAML and populates `_rules` dict without error
- [ ] `get_required_fields("discharge_summary")` returns the 5-item list defined in YAML
- [ ] `get_required_fields("unknown_type")` returns `[]` without raising
- [ ] `get_completeness_config()` returns the same cached instance on repeated calls
- [ ] `COMPLETENESS_CONFIG_PATH` env-var override works (used in unit tests to inject a temp YAML)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `pyyaml` | Library | Must be present in `pyproject.toml` / `requirements.txt` |
| TASK-026-002 | Task | `CompletenessValidator` imports `get_completeness_config()` |
