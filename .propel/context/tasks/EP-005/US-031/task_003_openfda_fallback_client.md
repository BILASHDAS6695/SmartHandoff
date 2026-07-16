---
id: TASK-003
title: "OpenFDA Fallback Drug Interaction Client"
user_story: US-031
epic: EP-005
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-002]
---

# TASK-003: OpenFDA Fallback Drug Interaction Client

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

When RxNav is unavailable (HTTP 503 or connection error), the system must fall back to the OpenFDA drug label API. OpenFDA is queried using the drug **name** (not CUI), and the `warnings` and `drug_interactions` sections of the label are parsed for interaction mentions. Results are returned in the same canonical shape as the RxNav client so the orchestrator (`DrugInteractionChecker`) treats both sources uniformly.

**Design references:**
- US-031 Definition of Done — `GET https://api.fda.gov/drug/label.json?search=warnings+interactions:{drug_name}`
- US-031 AC Scenario 3 — `source=OPENFDA` recorded in alert metadata
- design.md §4.1 — httpx async client

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 3 | OpenFDA queried with drug names; source recorded as `OPENFDA` |

---

## Implementation Steps

### 1. Create `backend/app/agents/medication_reconciliation/drug_interaction/openfda_client.py`

```python
"""OpenFDA drug label fallback client for drug-drug interaction queries.

Used when RxNav is unavailable. Queries the OpenFDA drug label endpoint and
extracts interaction-related text from the ``warnings`` and
``drug_interactions`` sections.

Design refs:
    US-031 AC Scenario 3   — source=OPENFDA in alert metadata
    US-031 Definition of Done — GET https://api.fda.gov/drug/label.json
    design.md §4.1         — httpx async client
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENFDA_BASE_URL = "https://api.fda.gov/drug/label.json"
_REQUEST_TIMEOUT_SECONDS = 10.0


class OpenFDAUnavailableError(Exception):
    """Raised when OpenFDA returns a non-successful HTTP response.

    Attributes:
        status_code: HTTP status code returned by OpenFDA.
    """

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"OpenFDA returned HTTP {status_code}")
        self.status_code = status_code


def _extract_interaction_text(label: dict[str, Any]) -> str:
    """Extract interaction-relevant text from an OpenFDA drug label record.

    Checks ``drug_interactions`` first, then ``warnings`` as fallback.

    Args:
        label: Single label record from the OpenFDA ``results`` array.

    Returns:
        Combined interaction text (may be empty string if no sections found).
    """
    sections: list[str] = []

    drug_interactions = label.get("drug_interactions")
    if drug_interactions and isinstance(drug_interactions, list):
        sections.extend(drug_interactions)

    warnings = label.get("warnings")
    if warnings and isinstance(warnings, list):
        sections.extend(warnings)

    return " ".join(sections)


class OpenFDAInteractionClient:
    """Async fallback client for OpenFDA drug label interaction data.

    Queries by drug **name** rather than RxCUI.  Returns results in the same
    canonical dict shape as ``RxNavInteractionClient`` so downstream code
    treats both sources uniformly.

    Args:
        http_client: Optional shared ``httpx.AsyncClient``.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def get_interactions(
        self,
        drug_name: str,
    ) -> list[dict[str, Any]]:
        """Fetch drug label interaction sections for a single drug name.

        Args:
            drug_name: Generic or brand drug name (e.g. ``"Warfarin"``).

        Returns:
            List of interaction dicts (may be empty). Each dict contains:
                ``drug1``, ``description``, ``source``, ``severity``.
            Severity defaults to ``"UNKNOWN"`` — callers must handle this when
            OpenFDA does not expose structured severity.

        Raises:
            OpenFDAUnavailableError: For any non-2xx HTTP response.
            httpx.TimeoutException: If the request times out.
        """
        search_query = f"warnings+interactions:{drug_name}"
        params = {"search": search_query, "limit": "5"}

        logger.info("Calling OpenFDA fallback drug_name=%s", drug_name)

        async def _do_request(client: httpx.AsyncClient) -> list[dict[str, Any]]:
            response = await client.get(
                _OPENFDA_BASE_URL,
                params=params,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                logger.warning(
                    "OpenFDA returned non-200 status=%d drug_name=%s",
                    response.status_code,
                    drug_name,
                )
                raise OpenFDAUnavailableError(status_code=response.status_code)

            body = response.json()
            results = body.get("results", [])
            interactions: list[dict[str, Any]] = []

            for label in results:
                text = _extract_interaction_text(label)
                if text:
                    interactions.append(
                        {
                            "drug1": drug_name,
                            "drug2": None,
                            "description": text[:2000],  # guard against huge label text
                            "severity": "UNKNOWN",
                            "source": "OPENFDA",
                        }
                    )

            return interactions

        if self._client:
            return await _do_request(self._client)

        async with httpx.AsyncClient() as client:
            return await _do_request(client)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/drug_interaction/openfda_client.py` | Create |

---

## Validation

- [ ] `source` field is always `"OPENFDA"` in returned dicts
- [ ] HTTP 404 (no results) from OpenFDA → `OpenFDAUnavailableError`
- [ ] `drug_interactions` section preferred over `warnings` when both present
- [ ] Description capped at 2000 characters to avoid oversized payloads
- [ ] Empty drug name returns empty list without making HTTP call

---

## Definition of Done

- [ ] `openfda_client.py` implemented and peer-reviewed
- [ ] Unit tests in TASK-008 cover fallback path
- [ ] `source=OPENFDA` asserted in all test responses
