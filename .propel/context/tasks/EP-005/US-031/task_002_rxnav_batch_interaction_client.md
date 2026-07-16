---
id: TASK-002
title: "RxNav Batch Interaction API Client"
user_story: US-031
epic: EP-005
sprint: 2
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-001, US-030]
---

# TASK-002: RxNav Batch Interaction API Client

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 4 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

RxNav (NIH) provides a free REST API for drug-drug interaction lookup via RxNorm CUIs. This task implements an async HTTP client that calls the **batch interaction list endpoint** (`GET /REST/interaction/list.json?rxcuis={cuis}`), parses severity strings into the canonical `HIGH / MEDIUM / LOW` enum, and surfaces HTTP errors as typed exceptions for the fallback mechanism implemented in TASK-004.

RxNorm CUIs are available from the medication normalisation service built in US-030.

**Design references:**
- design.md §4.1 — Drug Interaction DB: RxNav / OpenFDA API
- US-031 Technical Notes — batch call up to 50 RxCUIs; sorted CUI pair Redis key
- US-031 AC Scenario 1 — HIGH interaction: `severity=HIGH`, `source=RXNAV`
- US-031 AC Scenario 3 — RxNav HTTP 503 triggers OpenFDA fallback

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | Warfarin + Aspirin resolved as `severity=HIGH` from RxNav |
| AC Scenario 3 | RxNav `HTTP 503` raises `RxNavUnavailableError`, enabling fallback |

---

## Implementation Steps

### 1. Create `backend/app/agents/medication_reconciliation/drug_interaction/rxnav_client.py`

```python
"""Async HTTP client for the RxNav drug-drug interaction list endpoint.

Calls: GET https://rxnav.nlm.nih.gov/REST/interaction/list.json?rxcuis={cuis}

Design refs:
    US-031 Technical Notes — batch lookup, up to 50 RxCUIs per request
    US-031 AC Scenario 1   — major/contraindicated → HIGH
    US-031 AC Scenario 3   — HTTP 503 raises RxNavUnavailableError
    design.md §4.1         — httpx async client; fhir.resources + httpx stack
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RXNAV_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
_INTERACTION_ENDPOINT = "/interaction/list.json"
_REQUEST_TIMEOUT_SECONDS = 10.0


class InteractionSeverity(str, Enum):
    """Canonical severity levels used across the interaction pipeline."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RxNavUnavailableError(Exception):
    """Raised when RxNav returns a non-successful HTTP response.

    Attributes:
        status_code: HTTP status code returned by RxNav.
    """

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"RxNav returned HTTP {status_code}")
        self.status_code = status_code


def _map_severity(rxnav_severity: str) -> InteractionSeverity:
    """Map RxNav severity string to canonical ``InteractionSeverity``.

    Mapping rules (US-031 Definition of Done):
        - ``major`` or ``contraindicated`` → HIGH
        - ``moderate``                     → MEDIUM
        - ``minor``  (or anything else)    → LOW

    Args:
        rxnav_severity: Severity label from RxNav response (case-insensitive).

    Returns:
        Canonical ``InteractionSeverity`` enum value.
    """
    normalised = rxnav_severity.strip().lower()
    if normalised in {"major", "contraindicated"}:
        return InteractionSeverity.HIGH
    if normalised == "moderate":
        return InteractionSeverity.MEDIUM
    return InteractionSeverity.LOW


def _parse_interactions(
    response_json: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract interaction records from the RxNav list response.

    Args:
        response_json: Parsed JSON body from the RxNav interaction list endpoint.

    Returns:
        List of interaction dicts, each containing:
            ``rxcui1``, ``rxcui2``, ``drug1``, ``drug2``,
            ``severity``, ``description``, ``source``.
    """
    interactions: list[dict[str, Any]] = []

    full_interaction_type_group = (
        response_json
        .get("fullInteractionTypeGroup", [])
    )

    for group in full_interaction_type_group:
        for interaction_type in group.get("fullInteractionType", []):
            for pair in interaction_type.get("interactionPair", []):
                concepts = pair.get("interactionConcept", [])
                if len(concepts) < 2:  # pragma: no cover
                    continue

                rxcui1 = concepts[0]["minConceptItem"]["rxcui"]
                drug1 = concepts[0]["minConceptItem"]["name"]
                rxcui2 = concepts[1]["minConceptItem"]["rxcui"]
                drug2 = concepts[1]["minConceptItem"]["name"]
                raw_severity = pair.get("severity", "minor")
                description = pair.get("description", "")

                interactions.append(
                    {
                        "rxcui1": rxcui1,
                        "rxcui2": rxcui2,
                        "drug1": drug1,
                        "drug2": drug2,
                        "severity": _map_severity(raw_severity).value,
                        "description": description,
                        "source": "RXNAV",
                    }
                )

    return interactions


class RxNavInteractionClient:
    """Async client for the RxNav interaction list API.

    Designed for **batch** lookup — pass all active discharge medication
    RxCUIs in a single call (up to 50) to minimise API round trips.

    Args:
        http_client: Optional shared ``httpx.AsyncClient``.  If not provided,
            a new client is created per request (acceptable for testing).
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def get_interactions(
        self, rxcuis: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch drug-drug interactions for a list of RxCUIs.

        Args:
            rxcuis: List of RxNorm CUI strings (max 50 per RxNav spec).

        Returns:
            List of interaction dicts (may be empty if no interactions found).

        Raises:
            RxNavUnavailableError: For any non-2xx HTTP response from RxNav.
            httpx.TimeoutException: If the request exceeds ``_REQUEST_TIMEOUT_SECONDS``.
        """
        if not rxcuis:
            return []

        cuis_param = " ".join(rxcuis)
        url = f"{_RXNAV_BASE_URL}{_INTERACTION_ENDPOINT}"
        params = {"rxcuis": cuis_param}

        logger.info(
            "Calling RxNav interaction API rxcui_count=%d", len(rxcuis)
        )

        async def _do_request(client: httpx.AsyncClient) -> list[dict[str, Any]]:
            response = await client.get(
                url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code != 200:
                logger.warning(
                    "RxNav returned non-200 status=%d", response.status_code
                )
                raise RxNavUnavailableError(status_code=response.status_code)
            return _parse_interactions(response.json())

        if self._client:
            return await _do_request(self._client)

        async with httpx.AsyncClient() as client:
            return await _do_request(client)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/drug_interaction/rxnav_client.py` | Create |

---

## Validation

- [ ] `_map_severity("major")` → `HIGH`
- [ ] `_map_severity("contraindicated")` → `HIGH`
- [ ] `_map_severity("moderate")` → `MEDIUM`
- [ ] `_map_severity("minor")` → `LOW`
- [ ] `RxNavUnavailableError` raised when RxNav returns HTTP 503
- [ ] Empty `rxcuis` list returns `[]` without making an HTTP call
- [ ] `source` field set to `"RXNAV"` in all returned records

---

## Definition of Done

- [ ] `rxnav_client.py` implemented and peer-reviewed
- [ ] Severity mapping verified against all four RxNav severity labels
- [ ] Unit tests in TASK-008 cover HTTP 503 → `RxNavUnavailableError`
