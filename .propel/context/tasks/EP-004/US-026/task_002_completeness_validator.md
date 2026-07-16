---
id: TASK-026-002
title: "Implement `CompletenessValidator` — Configurable Required-Field Checker"
user_story: US-026
epic: EP-004
sprint: 2
layer: Backend — Domain Service
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-026-001]
---

# TASK-026-002: Implement `CompletenessValidator` — Configurable Required-Field Checker

> **Story:** US-026 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Domain Service | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

`CompletenessValidator` is the core domain service for US-026. It accepts a `DischargeSummarySchema` instance (or any dict-serialisable Pydantic model), reads the required field list from `CompletenessConfig`, and returns a `CompletenessResult` value object indicating whether the document is `COMPLETE` or `INCOMPLETE` and listing any absent fields.

Both `null` and empty-string / empty-list values count as "missing" (per Technical Notes in US-026). The validator is a pure, stateless function object — it holds no DB session and performs no I/O, making it straightforward to unit test.

This validator is invoked by `DocumentationAgent.process()` as a post-generation step (TASK-026-004).

---

## Acceptance Criteria Addressed

| US-026 AC | Requirement |
|---|---|
| **Scenario 1** | Complete document → `completeness_status=COMPLETE` |
| **Scenario 2** | Missing `follow_up_instructions` → `completeness_status=INCOMPLETE`, `missing_fields=["follow_up_instructions"]` |
| **Scenario 3** | Field list sourced from `CompletenessConfig` — no code change required to add a new required field |

---

## Implementation Steps

### 1. Create `backend/agents/documentation/completeness_validator.py`

```python
"""
CompletenessValidator — stateless required-field checker for discharge documents.

Reads required fields from CompletenessConfig (TASK-026-001) and evaluates
whether a generated document contains all non-null, non-empty values for every
required field. Returns a CompletenessResult value object.

Design constraints:
- Pure function object: no I/O, no DB session, no LLM calls.
- Both None and empty string/list values are treated as missing (US-026 Technical Notes).
- The required_fields list is sourced from YAML config — adding a field requires no
  code change (US-026 Scenario 3).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from config.completeness_config import CompletenessConfig, get_completeness_config

logger = logging.getLogger(__name__)


class CompletenessStatus(str, Enum):
    """Document completeness verdict."""
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class CompletenessResult:
    """
    Immutable value object returned by CompletenessValidator.

    Attributes:
        status: COMPLETE if all required fields are present and non-empty;
                INCOMPLETE otherwise.
        missing_fields: Ordered list of field names that are null or empty.
                        Empty list when status is COMPLETE.
    """
    status: CompletenessStatus
    missing_fields: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Convenience predicate — True when status is COMPLETE."""
        return self.status == CompletenessStatus.COMPLETE


def _is_absent(value: Any) -> bool:
    """
    Return True if the field value should be considered missing.

    Rules (US-026 Technical Notes):
    - None → missing
    - Empty string ("") → missing
    - Empty list ([]) → missing
    - Any other value (non-empty string, non-empty list, dict, int, bool) → present
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


class CompletenessValidator:
    """
    Validates discharge document completeness against a configurable required-field list.

    Args:
        config: CompletenessConfig instance. Defaults to the module-level cached singleton.
        document_type: The document type key used to look up the required fields in config.
                       Defaults to 'discharge_summary'.
    """

    def __init__(
        self,
        config: CompletenessConfig | None = None,
        document_type: str = "discharge_summary",
    ) -> None:
        self._config = config or get_completeness_config()
        self._document_type = document_type
        self._required_fields: List[str] = self._config.get_required_fields(document_type)
        logger.debug(
            "CompletenessValidator initialised: document_type=%s required_fields=%s",
            document_type,
            self._required_fields,
        )

    def validate(self, document_data: Dict[str, Any]) -> CompletenessResult:
        """
        Evaluate whether the document contains all required fields.

        Args:
            document_data: Dict representation of the document. Typically obtained
                           via `summary.model_dump()` from a DischargeSummarySchema.

        Returns:
            CompletenessResult with COMPLETE status and empty missing_fields list,
            or INCOMPLETE status with the list of absent field names.
        """
        missing: List[str] = []

        for field_name in self._required_fields:
            value = document_data.get(field_name)
            if _is_absent(value):
                missing.append(field_name)
                logger.debug("CompletenessValidator: field '%s' is absent or empty", field_name)

        if missing:
            logger.info(
                "CompletenessValidator: document INCOMPLETE — missing_fields=%s",
                missing,
            )
            return CompletenessResult(
                status=CompletenessStatus.INCOMPLETE,
                missing_fields=missing,
            )

        logger.info("CompletenessValidator: document COMPLETE")
        return CompletenessResult(status=CompletenessStatus.COMPLETE, missing_fields=[])
```

### 2. Export from `agents/documentation/__init__.py`

Add the new symbols alongside existing exports:

```python
from agents.documentation.completeness_validator import (
    CompletenessValidator,
    CompletenessResult,
    CompletenessStatus,
)

__all__ = [
    # existing
    "DischargeSummarySchema",
    "GenerationType",
    # new
    "CompletenessValidator",
    "CompletenessResult",
    "CompletenessStatus",
]
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/agents/documentation/completeness_validator.py` |
| **Update** | `backend/agents/documentation/__init__.py` |

---

## Definition of Done

- [ ] `CompletenessValidator` class implemented with `validate(document_data: dict) -> CompletenessResult`
- [ ] `_is_absent()` correctly treats `None`, `""`, `[]`, `{}` as missing
- [ ] `CompletenessResult` is a frozen dataclass with `status` and `missing_fields` fields
- [ ] `is_complete` property returns `True` only when `status == COMPLETE`
- [ ] Validator reads field list from `CompletenessConfig`; no field names hardcoded in validator
- [ ] All symbols exported from `agents/documentation/__init__.py`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-026-001 | Task | `CompletenessConfig` and `get_completeness_config()` must exist |
| TASK-026-006 | Task | Unit tests for this class live in TASK-026-006 |
