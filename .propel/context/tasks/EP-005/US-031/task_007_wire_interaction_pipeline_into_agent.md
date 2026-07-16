---
id: TASK-007
title: "Medication Reconciliation Agent — Wire DrugInteractionChecker into Agent Pipeline"
user_story: US-031
epic: EP-005
sprint: 2
layer: Backend / AI Agent
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-031/TASK-004, US-031/TASK-005, US-030]
---

# TASK-007: Medication Reconciliation Agent — Wire DrugInteractionChecker into Agent Pipeline

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 4 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `DrugInteractionChecker` (TASK-004) and `POST /api/v1/encounters/{id}/alerts` endpoint (TASK-005) exist as independent units. This task wires them into the **Medication Reconciliation Agent's** post-reconciliation pipeline, which is triggered after US-030 completes RxNorm normalisation. The agent must:

1. Load the active discharge medication list (with RxCUIs from US-030).
2. Invoke `DrugInteractionChecker.check()`.
3. For every `HIGH`-severity interaction found, call `POST /api/v1/encounters/{id}/alerts` with `priority=IMMEDIATE`.
4. For `MEDIUM`/`LOW` interactions, call the same endpoint with `priority=STANDARD`.
5. If `interaction_check_status=INCOMPLETE`, create a single MEDIUM alert ("manual review required").
6. Emit the overall check status back to the Pub/Sub `adt-events` acknowledgement so the Transition Coordinator Agent can track SLA compliance.

The entire pipeline (reconciliation trigger → interaction check → alert creation) must complete within 60 seconds per US-031 AC Scenario 1.

**Design references:**
- design.md §3.2 — Agent container pattern (LangChain, Pub/Sub subscription)
- design.md §3.1 — Medication Reconciliation Agent responsibility
- ADR-004 — LangChain as agent framework; structured Pydantic output
- US-031 Technical Notes — HIGH alert must use `IMMEDIATE` in Pub/Sub

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | Alert created and Pub/Sub message published within 60 s end-to-end |
| AC Scenario 3 | OpenFDA fallback result triggers alert with `source=OPENFDA` |
| AC Scenario 4 | INCOMPLETE status → single MEDIUM alert, no CRITICAL suppression |

---

## Implementation Steps

### 1. Create `backend/app/agents/medication_reconciliation/interaction_pipeline.py`

```python
"""Post-reconciliation drug interaction pipeline for the Medication Reconciliation Agent.

Invoked after US-030 normalisation is complete.  Runs DrugInteractionChecker,
maps results to alert payloads, and posts to the encounters alerts endpoint.

Design refs:
    US-031 AC Scenarios 1, 3, 4
    design.md §3.2   — Agent container pattern
    ADR-004          — LangChain structured output; Pydantic schema enforcement
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.agents.medication_reconciliation.drug_interaction.checker import (
    DischargedMedication,
    DrugInteractionChecker,
    DrugInteractionResult,
)

logger = logging.getLogger(__name__)

_ALERTS_ENDPOINT_TEMPLATE = "/api/v1/encounters/{encounter_id}/alerts"


class InteractionPipeline:
    """Orchestrates post-reconciliation drug interaction checking and alerting.

    Args:
        checker: Configured ``DrugInteractionChecker`` instance.
        api_client: Async HTTP client pre-configured with the API base URL and
            a service-account JWT (internal service-to-service call).
    """

    def __init__(
        self,
        checker: DrugInteractionChecker,
        api_client: httpx.AsyncClient,
    ) -> None:
        self._checker = checker
        self._api = api_client

    async def run(
        self,
        encounter_id: uuid.UUID,
        medications: list[DischargedMedication],
    ) -> dict[str, Any]:
        """Run interaction check and create pharmacist alerts.

        Args:
            encounter_id: UUID of the discharge encounter.
            medications: Active discharge medication list (with RxCUIs).

        Returns:
            Summary dict:
                ``interaction_check_status``, ``alerts_created``,
                ``high_severity_count``.
        """
        logger.info(
            "Starting interaction pipeline encounter_id=%s med_count=%d",
            encounter_id,
            len(medications),
        )

        result: DrugInteractionResult = await self._checker.check(medications)

        alerts_created = 0
        high_count = 0

        if result.interaction_check_status == "INCOMPLETE":
            await self._post_alert(
                encounter_id=encounter_id,
                severity="MEDIUM",
                drug_pair=None,
                description=result.degradation_notice,
                source="SYSTEM",
                check_status="INCOMPLETE",
            )
            alerts_created += 1
        else:
            for interaction in result.interactions:
                severity = interaction.get("severity", "LOW")
                if severity not in {"HIGH", "MEDIUM", "LOW"}:
                    severity = "LOW"

                await self._post_alert(
                    encounter_id=encounter_id,
                    severity=severity,
                    drug_pair=[interaction.get("drug1"), interaction.get("drug2")],
                    description=interaction.get("description"),
                    source=interaction.get("source", "RXNAV"),
                    check_status="COMPLETE",
                    metadata={"rxcui1": interaction.get("rxcui1"),
                               "rxcui2": interaction.get("rxcui2")},
                )
                alerts_created += 1
                if severity == "HIGH":
                    high_count += 1

        logger.info(
            "Interaction pipeline complete encounter_id=%s alerts=%d high=%d status=%s",
            encounter_id,
            alerts_created,
            high_count,
            result.interaction_check_status,
        )

        return {
            "interaction_check_status": result.interaction_check_status,
            "alerts_created": alerts_created,
            "high_severity_count": high_count,
        }

    async def _post_alert(
        self,
        encounter_id: uuid.UUID,
        severity: str,
        drug_pair: list[str | None] | None,
        description: str | None,
        source: str,
        check_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """POST a single pharmacist alert to the encounters alerts endpoint.

        Args:
            encounter_id: Target encounter UUID.
            severity: ``HIGH``, ``MEDIUM``, or ``LOW``.
            drug_pair: Two-element list of drug names (or ``None``).
            description: Interaction description text.
            source: ``RXNAV``, ``OPENFDA``, or ``SYSTEM``.
            check_status: ``COMPLETE`` or ``INCOMPLETE``.
            metadata: Additional key-value metadata.

        Raises:
            httpx.HTTPStatusError: If the alerts endpoint returns a non-2xx response.
        """
        endpoint = _ALERTS_ENDPOINT_TEMPLATE.format(encounter_id=encounter_id)
        payload: dict[str, Any] = {
            "alert_type": "PHARMACIST_ALERT",
            "severity": severity,
            "drug_pair": [d for d in (drug_pair or []) if d is not None] or None,
            "interaction_description": description,
            "source": source,
            "interaction_check_status": check_status,
            "metadata": metadata,
        }
        response = await self._api.post(endpoint, json=payload)
        response.raise_for_status()
        logger.debug("Alert posted encounter_id=%s severity=%s", encounter_id, severity)
```

### 2. Register pipeline in the agent Pub/Sub subscriber

In `backend/app/agents/medication_reconciliation/subscriber.py`, after normalisation completes (US-030), invoke:

```python
from app.agents.medication_reconciliation.interaction_pipeline import InteractionPipeline

# After RxNorm normalisation is confirmed:
pipeline = InteractionPipeline(checker=checker, api_client=internal_api_client)
summary = await pipeline.run(
    encounter_id=encounter.id,
    medications=discharge_medications,
)
logger.info("Interaction pipeline summary: %s", summary)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/interaction_pipeline.py` | Create |
| `backend/app/agents/medication_reconciliation/subscriber.py` | Update — invoke `InteractionPipeline.run()` after normalisation |

---

## Validation

- [ ] `InteractionPipeline.run()` calls `DrugInteractionChecker.check()` once per invocation
- [ ] Each `HIGH` interaction triggers `_post_alert` with `severity=HIGH`
- [ ] `INCOMPLETE` result → exactly one MEDIUM alert posted with `source=SYSTEM`
- [ ] Summary dict contains correct `alerts_created` and `high_severity_count`
- [ ] End-to-end timing (Pub/Sub receipt → last alert POST) ≤ 60 seconds under test load

---

## Definition of Done

- [ ] `interaction_pipeline.py` implemented and peer-reviewed
- [ ] `subscriber.py` updated to invoke pipeline post-normalisation
- [ ] Integration smoke test confirms alert appears in pharmacist dashboard
- [ ] No CRITICAL alert silently suppressed during INCOMPLETE path
