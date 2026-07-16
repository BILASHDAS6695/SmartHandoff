---
id: TASK-002
title: "Implement Field-Level JSON Diff Engine for Document Change Tracking"
user_story: US-028
epic: EP-004
sprint: 2
layer: Backend — Business Logic
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-002: Implement Field-Level JSON Diff Engine for Document Change Tracking

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Business Logic | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 Scenario 2 requires the backend to compute a field-level diff between the previous
`Document.content` and the incoming edited payload, then produce one `ChangeLogEntry` per
changed field. This diff engine is a pure utility module with no external dependencies — it
compares top-level section keys in the structured document JSON and records changes only when
`old_value != new_value`.

This module is called exclusively from the PATCH `/api/v1/documents/{id}` handler (TASK-003).

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 2** | JSON diff entry produced per changed field with `old_value`, `new_value`, `author_id`, `timestamp` |

---

## Implementation Steps

### 1. Create `backend/services/document_diff.py`

```python
"""
Field-level JSON diff engine for document change tracking.

Compares the stored document content against the incoming edited payload and
produces a list of ChangeLogEntry records — one per changed top-level field.

Design decisions:
- Top-level key comparison only: discharge summary sections are atomic strings
  or small objects; deep-diff is deferred to Phase 2.
- Strict equality (==): avoids false negatives from whitespace normalisation;
  callers must normalise before passing if needed.
- No external diff library dependency: keeps the agent container lightweight.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from api.schemas.document_schemas import ChangeLogEntry

logger = logging.getLogger(__name__)


def compute_field_diff(
    stored_content: dict[str, Any],
    updated_content: dict[str, Any],
    author_id: UUID,
) -> list[ChangeLogEntry]:
    """
    Compare `stored_content` against `updated_content` at the top-level field level.

    Args:
        stored_content: The current `Document.content` value (decrypted dict).
        updated_content: The incoming edited content from the PATCH request body.
        author_id: UUID of the authenticated user performing the edit.

    Returns:
        List of `ChangeLogEntry` — one entry per field where
        `updated_content[field] != stored_content.get(field)`.
        Returns an empty list when no fields changed.

    Raises:
        ValueError: If either argument is not a dict.
    """
    if not isinstance(stored_content, dict):
        raise ValueError(f"stored_content must be a dict, got {type(stored_content).__name__}")
    if not isinstance(updated_content, dict):
        raise ValueError(f"updated_content must be a dict, got {type(updated_content).__name__}")

    timestamp = datetime.now(timezone.utc)
    entries: list[ChangeLogEntry] = []

    all_keys = set(stored_content.keys()) | set(updated_content.keys())

    for field in sorted(all_keys):  # Deterministic order for auditability
        old_val = stored_content.get(field)
        new_val = updated_content.get(field)

        if old_val != new_val:
            entries.append(
                ChangeLogEntry(
                    field=field,
                    old_value=old_val,
                    new_value=new_val,
                    author_id=author_id,
                    timestamp=timestamp,
                )
            )
            logger.debug(
                "Change detected in field '%s' by author %s", field, author_id
            )

    return entries


def apply_diff_to_change_log(
    existing_log: list[dict],
    new_entries: list[ChangeLogEntry],
) -> list[dict]:
    """
    Append `new_entries` to the existing `change_log` list.

    Converts `ChangeLogEntry` objects to plain dicts for JSONB storage.
    Preserves existing entries (append-only semantics).

    Args:
        existing_log: Current `Document.change_log` list (may be empty).
        new_entries: New `ChangeLogEntry` objects to append.

    Returns:
        Updated list of dicts ready for JSONB persistence.
    """
    serialised = [
        entry.model_dump(mode="json") for entry in new_entries
    ]
    return existing_log + serialised
```

---

## File Locations

| File | Path |
|---|---|
| `document_diff.py` | `backend/services/document_diff.py` |

---

## Validation Checklist

- [ ] `compute_field_diff` returns `[]` when `stored_content == updated_content`
- [ ] `compute_field_diff` produces one entry per changed field (not one entry for the whole document)
- [ ] `ChangeLogEntry.timestamp` is timezone-aware UTC
- [ ] `apply_diff_to_change_log` never mutates `existing_log` in-place (returns a new list)
- [ ] `compute_field_diff` raises `ValueError` for non-dict inputs
- [ ] Field ordering is deterministic (sorted keys) for reproducible test assertions
- [ ] No external diff library imported (pure stdlib + project schemas)

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-001` | `ChangeLogEntry` Pydantic schema must be available |
