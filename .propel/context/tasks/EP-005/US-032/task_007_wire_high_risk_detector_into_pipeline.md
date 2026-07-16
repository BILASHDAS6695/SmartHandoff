---
id: TASK-007
title: "Wire HighRiskDrugClassDetector into Medication Reconciliation Agent Pipeline"
user_story: US-032
epic: EP-005
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-032/TASK-002, US-032/TASK-003, US-031/TASK-007]
---

# TASK-007: Wire HighRiskDrugClassDetector into Medication Reconciliation Agent Pipeline

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-031 TASK-007 created the `InteractionPipeline` class that wires drug interaction detection into the Medication Reconciliation Agent. US-032 extends that pipeline to run `HighRiskDrugClassDetector` (TASK-002) **in parallel** with the interaction check and POST a `HIGH_RISK_DRUG_CLASS` alert to `POST /api/v1/encounters/{id}/alerts` for every match.

Per US-032 Technical Notes, alert creation is **additive**: a drug already flagged by the interaction checker can also trigger a `HIGH_RISK_DRUG_CLASS` alert. No deduplication is applied.

The pipeline extension must:
1. Run `HighRiskDrugClassDetector.detect()` on the same discharge medication list.
2. Call `POST /api/v1/encounters/{id}/alerts` once per `HighRiskDrugMatch`.
3. Include the `drug_class`, `drug_name`, and `severity=HIGH` fields in the alert payload.
4. Proceed regardless of the interaction check result — high-risk detection is unconditional.

**Design references:**
- US-032 Technical Notes — ADDITIVE alerts; unconditional detection
- US-032 AC Scenario 1 — alert created regardless of interaction severity
- design.md §3.1 — Medication Reconciliation Agent (Cloud Run, LangChain)
- US-031/TASK-007 — existing `InteractionPipeline` class location

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 1** | `PHARMACIST_ALERT` of type `HIGH_RISK_DRUG_CLASS` created for Warfarin regardless of interaction result |
| **DoD** | `HighRiskDrugClassDetector` wired into the Medication Reconciliation Agent |

---

## Implementation Steps

### 1. Extend `backend/app/agents/medication_reconciliation/pipeline.py`

Locate the existing `InteractionPipeline` class (from US-031/TASK-007) and add the `_run_high_risk_detection` step:

```python
# --- New import (add to existing imports block) ---
from app.agents.medication_reconciliation.high_risk.detector import (
    HighRiskDrugClassDetector,
    HighRiskDrugMatch,
)
from app.schemas.pharmacist_alert import HighRiskDrugClassAlertCreate


# --- Add method to InteractionPipeline class ---

    async def _run_high_risk_detection(
        self, medications: list[DischargedMedication]
    ) -> list[HighRiskDrugMatch]:
        """Detect ISMP high-alert medications and post alerts for each match.

        Runs unconditionally and in parallel with the interaction check.
        Alert creation is ADDITIVE: a drug flagged by interaction check AND
        high-risk detection will produce two separate alert records.

        Args:
            medications: Discharge medication list from US-030 normalisation.

        Returns:
            List of :class:`HighRiskDrugMatch` for audit/logging.

        Design refs:
            US-032 AC Scenario 1   — unconditional; ADDITIVE
            US-032 Technical Notes — case-insensitive name match
        """
        detector = HighRiskDrugClassDetector()
        matches = detector.detect(medications)

        for match in matches:
            payload = HighRiskDrugClassAlertCreate(
                alert_type="HIGH_RISK_DRUG_CLASS",
                drug_class=match.drug_class,
                drug_name=match.drug_name,
                severity="HIGH",
            )
            await self._post_alert(
                encounter_id=self._encounter_id,
                payload=payload.model_dump(),
            )
            logger.info(
                "HIGH_RISK_DRUG_CLASS alert posted: encounter=%s drug=%r class=%s",
                self._encounter_id,
                match.drug_name,
                match.drug_class,
            )

        return matches
```

### 2. Update `InteractionPipeline.run()` to call high-risk detection in parallel

```python
    async def run(self, medications: list[DischargedMedication]) -> PipelineResult:
        """Run interaction check and high-risk detection concurrently.

        Args:
            medications: Normalised discharge medication list from US-030.

        Returns:
            :class:`PipelineResult` with interaction and high-risk outcomes.
        """
        interaction_task = asyncio.create_task(
            self._run_interaction_check(medications)
        )
        high_risk_task = asyncio.create_task(
            self._run_high_risk_detection(medications)
        )

        interaction_result, high_risk_matches = await asyncio.gather(
            interaction_task,
            high_risk_task,
            return_exceptions=True,
        )

        # High-risk detection failure must not block the interaction result
        if isinstance(high_risk_matches, Exception):
            logger.error(
                "High-risk detection failed for encounter=%s: %s",
                self._encounter_id,
                high_risk_matches,
            )
            high_risk_matches = []

        return PipelineResult(
            interaction_result=interaction_result,
            high_risk_matches=high_risk_matches,
        )
```

### 3. Update `PipelineResult` dataclass

```python
from app.agents.medication_reconciliation.high_risk.detector import HighRiskDrugMatch

@dataclass
class PipelineResult:
    """Combined outcome of the medication reconciliation pipeline."""
    interaction_result: DrugInteractionResult
    high_risk_matches: list[HighRiskDrugMatch] = field(default_factory=list)
```

---

## Validation

- [ ] Pipeline with `Warfarin 5mg` in discharge list produces a `HIGH_RISK_DRUG_CLASS` alert posted to `POST /api/v1/encounters/{id}/alerts` — even when no drug interaction is found
- [ ] Pipeline with both `Warfarin 5mg` and `Oxycodone 10mg` posts two separate `HIGH_RISK_DRUG_CLASS` alerts (one per drug)
- [ ] High-risk detection runs concurrently with interaction check (both tasks started before `await gather`)
- [ ] If `HighRiskDrugClassDetector` raises an exception, `interaction_result` is still returned correctly (no blocking)
- [ ] `Amoxicillin 500mg` (non-high-risk drug) produces zero `HIGH_RISK_DRUG_CLASS` alerts
- [ ] `PipelineResult.high_risk_matches` is populated with the list of `HighRiskDrugMatch` objects

---

## Files Changed

| Action | Path |
|--------|------|
| Modify | `backend/app/agents/medication_reconciliation/pipeline.py` |
