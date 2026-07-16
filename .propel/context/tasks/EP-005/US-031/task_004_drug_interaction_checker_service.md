---
id: TASK-004
title: "DrugInteractionChecker Service — Cache → RxNav → OpenFDA Orchestration"
user_story: US-031
epic: EP-005
sprint: 2
layer: Backend
estimate: 5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-031/TASK-001, US-031/TASK-002, US-031/TASK-003]
---

# TASK-004: DrugInteractionChecker Service — Cache → RxNav → OpenFDA Orchestration

> **Story:** US-031 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 5 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task assembles the three lower-level components (cache, RxNav client, OpenFDA client) into the `DrugInteractionChecker` service. The service:

1. Generates all unique drug pairs from the discharge medication list.
2. Checks the Redis cache for each pair (cache hit → return immediately).
3. On cache miss, calls RxNav batch API; caches results.
4. If RxNav raises `RxNavUnavailableError`, falls back to OpenFDA for each drug name.
5. If both sources fail, sets `interaction_check_status=INCOMPLETE` on the reconciliation record and returns a MEDIUM-severity degradation notice.

The service also applies the severity filter: only `HIGH` interactions trigger the `IMMEDIATE` notification path in TASK-006.

**Design references:**
- US-031 Technical Notes — batch call with all active discharge CUIs
- US-031 AC Scenarios 1–4
- design.md §3.1 — Medication Reconciliation Agent (Cloud Run, LangChain)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | HIGH-severity interaction returned with `source=RXNAV` |
| AC Scenario 2 | Cache hit path returns without calling RxNav |
| AC Scenario 3 | RxNav 503 → OpenFDA fallback; `source=OPENFDA` |
| AC Scenario 4 | Both APIs fail → `interaction_check_status=INCOMPLETE`, MEDIUM alert |

---

## Implementation Steps

### 1. Create `backend/app/agents/medication_reconciliation/drug_interaction/checker.py`

```python
"""DrugInteractionChecker — orchestrates cache → RxNav → OpenFDA lookup.

Generates all unique discharge medication pairs, checks Redis cache, calls
RxNav (batch), and falls back to OpenFDA if RxNav is unavailable.

Design refs:
    US-031 AC Scenarios 1–4
    US-031 Technical Notes — batch call; sorted CUI key; IMMEDIATE for HIGH
    design.md §3.1         — Medication Reconciliation Agent
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.medication_reconciliation.drug_interaction.cache import (
    DrugInteractionCache,
)
from app.agents.medication_reconciliation.drug_interaction.openfda_client import (
    OpenFDAInteractionClient,
    OpenFDAUnavailableError,
)
from app.agents.medication_reconciliation.drug_interaction.rxnav_client import (
    RxNavInteractionClient,
    RxNavUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class DrugInteractionResult:
    """Structured outcome of a drug interaction check.

    Attributes:
        interactions: List of detected interaction records.
        interaction_check_status: ``COMPLETE`` or ``INCOMPLETE``.
        degradation_notice: Human-readable notice when status is INCOMPLETE.
    """

    interactions: list[dict[str, Any]] = field(default_factory=list)
    interaction_check_status: str = "COMPLETE"
    degradation_notice: str | None = None


@dataclass
class DischargedMedication:
    """Minimal medication descriptor needed for interaction checking.

    Attributes:
        rxcui: RxNorm CUI (from US-030 normalisation).
        drug_name: Generic drug name used for OpenFDA fallback.
    """

    rxcui: str
    drug_name: str


class DrugInteractionChecker:
    """Service that detects drug-drug interactions for a discharge medication list.

    Lookup order per drug pair:
        1. Redis cache  — returns immediately on hit
        2. RxNav batch API — caches result on success
        3. OpenFDA per-drug — used when RxNav raises ``RxNavUnavailableError``
        4. Offline degradation — when both APIs fail

    Args:
        cache: ``DrugInteractionCache`` wrapping Cloud Memorystore Redis.
        rxnav_client: ``RxNavInteractionClient``.
        openfda_client: ``OpenFDAInteractionClient``.
    """

    def __init__(
        self,
        cache: DrugInteractionCache,
        rxnav_client: RxNavInteractionClient,
        openfda_client: OpenFDAInteractionClient,
    ) -> None:
        self._cache = cache
        self._rxnav = rxnav_client
        self._openfda = openfda_client

    async def check(
        self, medications: list[DischargedMedication]
    ) -> DrugInteractionResult:
        """Run interaction checks for all active discharge medications.

        Args:
            medications: List of ``DischargedMedication`` objects (max 50 per
                RxNav batch limit).

        Returns:
            ``DrugInteractionResult`` containing all found interactions and
            the check status.
        """
        if len(medications) < 2:
            logger.info("Fewer than 2 medications — no interaction check needed")
            return DrugInteractionResult()

        all_interactions: list[dict[str, Any]] = []

        # --- Step 1: Check Redis cache for each unique pair ---
        uncached_pairs: list[tuple[DischargedMedication, DischargedMedication]] = []
        for med_a, med_b in itertools.combinations(medications, 2):
            cached = await self._cache.get(med_a.rxcui, med_b.rxcui)
            if cached is not None:
                all_interactions.extend(cached.get("interactions", []))
            else:
                uncached_pairs.append((med_a, med_b))

        if not uncached_pairs:
            logger.info("All drug pairs served from cache pair_count=%d", len(all_interactions))
            return DrugInteractionResult(interactions=all_interactions)

        # --- Step 2: RxNav batch call for uncached pairs ---
        unique_rxcuis = list(
            {med.rxcui for pair in uncached_pairs for med in pair}
        )
        rxnav_failed = False

        try:
            rxnav_results = await self._rxnav.get_interactions(unique_rxcuis)

            # Partition results by CUI pair and populate cache
            for med_a, med_b in uncached_pairs:
                pair_results = [
                    r
                    for r in rxnav_results
                    if {r["rxcui1"], r["rxcui2"]} == {med_a.rxcui, med_b.rxcui}
                ]
                await self._cache.set(
                    med_a.rxcui, med_b.rxcui, {"interactions": pair_results}
                )
                all_interactions.extend(pair_results)

        except (RxNavUnavailableError, Exception) as exc:
            logger.warning("RxNav unavailable — activating OpenFDA fallback: %s", exc)
            rxnav_failed = True

        # --- Step 3: OpenFDA fallback for each unique drug name ---
        if rxnav_failed:
            openfda_failed = False
            unique_drugs = list(
                {med.drug_name for pair in uncached_pairs for med in pair}
            )

            try:
                openfda_tasks = [
                    self._openfda.get_interactions(name) for name in unique_drugs
                ]
                results_per_drug = await asyncio.gather(
                    *openfda_tasks, return_exceptions=True
                )

                for drug_results in results_per_drug:
                    if isinstance(drug_results, Exception):
                        logger.warning("OpenFDA call failed: %s", drug_results)
                        openfda_failed = True
                    else:
                        all_interactions.extend(drug_results)

            except Exception as exc:
                logger.error("OpenFDA fallback failed entirely: %s", exc)
                openfda_failed = True

            # --- Step 4: Offline degradation ---
            if openfda_failed:
                logger.error(
                    "Both RxNav and OpenFDA unavailable — marking INCOMPLETE"
                )
                return DrugInteractionResult(
                    interactions=all_interactions,
                    interaction_check_status="INCOMPLETE",
                    degradation_notice=(
                        "Interaction check unavailable — manual review required"
                    ),
                )

        return DrugInteractionResult(interactions=all_interactions)
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/drug_interaction/checker.py` | Create |

---

## Validation

- [ ] Single medication list (`len < 2`) returns `COMPLETE` with no interactions
- [ ] Cache hit path: `RxNavInteractionClient.get_interactions` never called (mock asserts call count = 0)
- [ ] Cache miss → RxNav success → results cached and returned
- [ ] RxNav 503 → OpenFDA fallback called per unique drug name
- [ ] Both fail → `interaction_check_status="INCOMPLETE"`, `degradation_notice` set
- [ ] `HIGH`-severity interactions present in result when Warfarin + Aspirin pair processed

---

## Definition of Done

- [ ] `checker.py` implemented and peer-reviewed
- [ ] All four AC scenarios exercised via unit tests (TASK-008)
- [ ] No silent suppression of CRITICAL alerts during degradation
