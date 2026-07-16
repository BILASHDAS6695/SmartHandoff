# TASK-004: MedicationReconciliationAgent — Three-way Comparison, Duplicate & Missing Detection

> **Story:** US-030 | **Effort:** 10 hours | **Layer:** Backend — AI Agent  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement the `MedicationReconciliationAgent` that extends `BaseAgent`, orchestrates the FHIR fetch → normalisation → three-way comparison pipeline, applies duplicate and missing-chronic-medication detection, and persists categorised results to the `medication` table.

---

## Context

This is the core agent task for US-030. It wires together TASK-002 (FHIR fetcher) and TASK-003 (RxNorm normaliser) into a LangChain-based agent that categorises every medication as `CONTINUED`, `NEW`, `STOPPED`, or `DOSE_CHANGED`, flags duplicates and undocumented stops, and writes results to the database. Downstream TASK-005 exposes these results via API.

**Upstream Dependencies:**
- US-024: `BaseAgent` framework with Pub/Sub consumer, structured output, and DB write helpers
- TASK-001: `Medication` ORM model, `ReconciliationCategory`, `ReconciliationFlag` enums
- TASK-002: `FHIRMedicationFetcher`
- TASK-003: `RxNormNormaliser`, `DoseParser`

---

## Scope

### In Scope

1. **`MedicationReconciliationAgent`** — `backend/app/agents/medication_reconciliation/agent.py`:
   - Extends `BaseAgent`
   - Entry point: `async run(encounter_id: str) -> list[Medication]`
   - Calls `FHIRMedicationFetcher.fetch_all`
   - Calls `RxNormNormaliser.normalise_batch` for all unique drug names
   - Calls `DoseParser.parse_dose` for each entry
   - Runs `_compare` to categorise each drug
   - Runs `_detect_duplicates` to flag `DUPLICATE`
   - Runs `_detect_missing_chronic` to flag `STOPPED_WITHOUT_ORDER`
   - Persists `Medication` ORM records via async SQLAlchemy session

2. **Comparison algorithm** — `_compare` private method:
   - Build sets: `pre_admit_cuis`, `discharge_cuis` (keyed by CUI, fallback to name)
   - `CONTINUED`: drug in `pre_admit` AND `discharge`
   - `NEW`: drug in `discharge` only (not in `pre_admit`)
   - `STOPPED`: drug in `pre_admit`, absent from `discharge`
   - `DOSE_CHANGED`: CUI present in both `pre_admit` and `discharge` but parsed dose differs

3. **Duplicate detection** — `_detect_duplicates`:
   - Group discharge meds by `rxnorm_cui` (if available) else by normalised name
   - If 2+ discharge entries share same CUI **and** same route → flag both as `DUPLICATE`

4. **Missing chronic detection** — `_detect_missing_chronic`:
   - For each `STOPPED` drug: query FHIR `MedicationRequest?subject={patient_id}&medication={cui}&status=stopped`
   - If no documented stop order found → upgrade flag to `STOPPED_WITHOUT_ORDER`

5. **Pharmacist alert creation** — `_create_alerts`:
   - `STOPPED_WITHOUT_ORDER` → create `PharmacistAlert` with `severity=HIGH`
   - `DUPLICATE` → create `PharmacistAlert` with `severity=MEDIUM`
   - Alerts published to Pub/Sub `pharmacist-alerts` topic

### Out of Scope

- FastAPI endpoint (TASK-005)
- Unit tests (TASK-006)
- Drug interaction detection (separate US-031)

---

## Acceptance Criteria

### AC1: Three-way Comparison Categorises All Drugs
**Given** 5 pre-admit meds, 7 inpatient meds, 4 discharge meds  
**When** `run(encounter_id)` completes  
**Then** every medication in the union has exactly one `ReconciliationCategory` assigned

### AC2: `CONTINUED` Category
**Given** `Metformin 500mg` appears on pre-admit AND discharge lists with the same CUI  
**When** comparison runs  
**Then** `Metformin` record has `reconciliation_category = CONTINUED`

### AC3: `NEW` Category
**Given** `Lisinopril 10mg` appears only on the discharge list  
**When** comparison runs  
**Then** `Lisinopril` record has `reconciliation_category = NEW`

### AC4: `STOPPED` Category
**Given** `Atorvastatin 40mg` appears on pre-admit but NOT on discharge  
**When** comparison runs  
**Then** `Atorvastatin` record has `reconciliation_category = STOPPED`

### AC5: `DOSE_CHANGED` Category
**Given** `Metoprolol` has CUI `866514` on pre-admit with dose `25mg` and discharge with dose `50mg`  
**When** comparison runs  
**Then** `Metoprolol` record has `reconciliation_category = DOSE_CHANGED`

### AC6: `DUPLICATE` Flag
**Given** `Metformin 500mg oral` and `Metformin XR 500mg oral` share the same RxNorm CUI and route  
**When** `_detect_duplicates` runs  
**Then** both entries have `ReconciliationFlag.DUPLICATE` in their `flags` array; a `PharmacistAlert` with `severity=MEDIUM` is created

### AC7: `STOPPED_WITHOUT_ORDER` Flag
**Given** `Atorvastatin 40mg` is `STOPPED` and FHIR returns no `MedicationRequest?status=stopped` for it  
**When** `_detect_missing_chronic` runs  
**Then** the entry has `ReconciliationFlag.STOPPED_WITHOUT_ORDER`; a `PharmacistAlert` with `severity=HIGH` is created

### AC8: Results Persisted to Database
**Given** reconciliation completes  
**When** agent `run` finishes  
**Then** `Medication` ORM records with `reconciliation_category`, `rxnorm_cui`, `flags`, `sources`, `dose_value`, `dose_unit`, `route`, `frequency` are written to the database

---

## Implementation Details

### File: `backend/app/agents/medication_reconciliation/agent.py`

```python
"""Medication Reconciliation Agent — three-way FHIR comparison."""

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.models.medication import (
    Medication,
    MedicationListSource,
    ReconciliationCategory,
    ReconciliationFlag,
)
from .fhir_fetcher import FHIRMedicationFetcher
from .models import RawMedicationEntry
from .rxnorm import RxNormNormaliser
from .dose_parser import parse_dose

logger = logging.getLogger(__name__)


class MedicationReconciliationAgent(BaseAgent):
    """
    Compares pre-admission, inpatient, and discharge FHIR medication lists
    and categorises every drug as CONTINUED | NEW | STOPPED | DOSE_CHANGED.

    Detects DUPLICATE and STOPPED_WITHOUT_ORDER conditions and creates
    pharmacist alerts for each.
    """

    agent_name = "medication_reconciliation"

    def __init__(
        self,
        fhir_fetcher: FHIRMedicationFetcher,
        normaliser: RxNormNormaliser,
        session: AsyncSession,
    ) -> None:
        super().__init__()
        self._fetcher = fhir_fetcher
        self._normaliser = normaliser
        self._session = session

    async def run(self, encounter_id: str) -> list[Medication]:
        """
        Execute full medication reconciliation for an encounter.
        Returns list of persisted Medication ORM records.
        """
        logger.info("Starting medication reconciliation for encounter %s", encounter_id)

        # Step 1: Fetch all three lists
        raw_lists = await self._fetcher.fetch_all(encounter_id)

        # Step 2: Normalise all drug names to RxNorm CUIs
        all_entries: list[RawMedicationEntry] = [
            entry for entries in raw_lists.values() for entry in entries
        ]
        unique_names = list({e.name for e in all_entries})
        cui_map = await self._normaliser.normalise_batch(unique_names)

        # Step 3: Parse doses
        for entry in all_entries:
            entry.dose_value, entry.dose_unit = parse_dose(entry.dose_string)
            entry.rxnorm_cui = cui_map.get(entry.name)

        # Step 4: Three-way comparison
        medications = self._compare(raw_lists)

        # Step 5: Flag duplicates and missing chronics
        self._detect_duplicates(medications)
        await self._detect_missing_chronic(medications, encounter_id)

        # Step 6: Create pharmacist alerts
        await self._create_alerts(medications, encounter_id)

        # Step 7: Persist to database
        now = datetime.now(timezone.utc)
        for med in medications:
            med.encounter_id = encounter_id
            med.reconciliation_completed_at = now
            self._session.add(med)
        await self._session.commit()

        logger.info(
            "Reconciliation complete for %s: %d medications categorised",
            encounter_id,
            len(medications),
        )
        return medications

    # ── Comparison ──────────────────────────────────────────────────────

    def _compare(
        self,
        raw_lists: dict[MedicationListSource, list[RawMedicationEntry]],
    ) -> list[Medication]:
        """Categorise each drug across pre-admit, inpatient, and discharge."""
        pre_admit = raw_lists.get(MedicationListSource.PRE_ADMIT, [])
        discharge = raw_lists.get(MedicationListSource.DISCHARGE, [])

        # Key = CUI if available, otherwise lowercased name
        def key(entry: RawMedicationEntry) -> str:
            return entry.rxnorm_cui or entry.name.lower().strip()

        pre_map: dict[str, RawMedicationEntry] = {key(e): e for e in pre_admit}
        dis_map: dict[str, RawMedicationEntry] = {key(e): e for e in discharge}

        all_keys = set(pre_map) | set(dis_map)
        medications: list[Medication] = []

        for drug_key in all_keys:
            in_pre = drug_key in pre_map
            in_dis = drug_key in dis_map

            pre_entry = pre_map.get(drug_key)
            dis_entry = dis_map.get(drug_key)
            entry = dis_entry or pre_entry

            sources = []
            if in_pre:
                sources.append(MedicationListSource.PRE_ADMIT)
            if any(e.rxnorm_cui == drug_key or key(e) == drug_key
                   for e in raw_lists.get(MedicationListSource.INPATIENT, [])):
                sources.append(MedicationListSource.INPATIENT)
            if in_dis:
                sources.append(MedicationListSource.DISCHARGE)

            category = self._determine_category(pre_entry, dis_entry, in_pre, in_dis)

            dose_value, dose_unit = (
                (entry.dose_value, entry.dose_unit) if hasattr(entry, "dose_value") else (None, None)
            )

            med = Medication(
                name=entry.name,
                rxnorm_cui=entry.rxnorm_cui,
                reconciliation_category=category,
                flags=[],
                dose_value=dose_value,
                dose_unit=dose_unit,
                route=entry.route,
                frequency=entry.frequency,
                sources=sources,
            )
            medications.append(med)

        return medications

    @staticmethod
    def _determine_category(
        pre: RawMedicationEntry | None,
        dis: RawMedicationEntry | None,
        in_pre: bool,
        in_dis: bool,
    ) -> ReconciliationCategory:
        if in_pre and in_dis:
            if pre and dis:
                pre_dose, _ = parse_dose(pre.dose_string)
                dis_dose, _ = parse_dose(dis.dose_string)
                if pre_dose is not None and dis_dose is not None and pre_dose != dis_dose:
                    return ReconciliationCategory.DOSE_CHANGED
            return ReconciliationCategory.CONTINUED
        if in_dis and not in_pre:
            return ReconciliationCategory.NEW
        return ReconciliationCategory.STOPPED  # in_pre and not in_dis

    # ── Duplicate Detection ──────────────────────────────────────────────

    def _detect_duplicates(self, medications: list[Medication]) -> None:
        """Flag discharge medications sharing CUI + route as DUPLICATE."""
        discharge_meds = [
            m for m in medications
            if MedicationListSource.DISCHARGE in m.sources
        ]
        grouped: dict[tuple, list[Medication]] = defaultdict(list)
        for med in discharge_meds:
            group_key = (med.rxnorm_cui or med.name.lower(), (med.route or "").lower())
            grouped[group_key].append(med)

        for group in grouped.values():
            if len(group) >= 2:
                for med in group:
                    if ReconciliationFlag.DUPLICATE not in med.flags:
                        med.flags = [*med.flags, ReconciliationFlag.DUPLICATE]

    # ── Missing Chronic Detection ────────────────────────────────────────

    async def _detect_missing_chronic(
        self, medications: list[Medication], encounter_id: str
    ) -> None:
        """
        For STOPPED medications with no documented stop order in FHIR,
        upgrade to STOPPED_WITHOUT_ORDER flag.
        """
        stopped_meds = [
            m for m in medications
            if m.reconciliation_category == ReconciliationCategory.STOPPED
        ]
        for med in stopped_meds:
            has_stop_order = await self._check_stop_order(med, encounter_id)
            if not has_stop_order:
                med.flags = [*med.flags, ReconciliationFlag.STOPPED_WITHOUT_ORDER]

    async def _check_stop_order(
        self, med: Medication, encounter_id: str
    ) -> bool:
        """
        Returns True if a MedicationRequest with status=stopped exists for this drug.
        """
        try:
            search_params = {"encounter": encounter_id, "status": "stopped"}
            if med.rxnorm_cui:
                search_params["code"] = f"http://www.nlm.nih.gov/research/umls/rxnorm|{med.rxnorm_cui}"
            bundle = await self._fetcher._client.search("MedicationRequest", search_params)
            return len(bundle.get("entry", [])) > 0
        except Exception as exc:
            logger.warning("Stop order check failed for %s: %s", med.name, exc)
            return False  # Treat as no stop order on error

    # ── Alert Creation ────────────────────────────────────────────────────

    async def _create_alerts(
        self, medications: list[Medication], encounter_id: str
    ) -> None:
        """Publish pharmacist alerts for flagged medications."""
        for med in medications:
            if ReconciliationFlag.STOPPED_WITHOUT_ORDER in med.flags:
                await self._publish_alert(
                    encounter_id=encounter_id,
                    drug_name=med.name,
                    flag=ReconciliationFlag.STOPPED_WITHOUT_ORDER,
                    severity="HIGH",
                )
            if ReconciliationFlag.DUPLICATE in med.flags:
                await self._publish_alert(
                    encounter_id=encounter_id,
                    drug_name=med.name,
                    flag=ReconciliationFlag.DUPLICATE,
                    severity="MEDIUM",
                )

    async def _publish_alert(
        self,
        encounter_id: str,
        drug_name: str,
        flag: ReconciliationFlag,
        severity: str,
    ) -> None:
        """Publish a pharmacist alert to the pharmacist-alerts Pub/Sub topic."""
        # Use BaseAgent Pub/Sub publish helper
        await self.publish_event(
            topic="pharmacist-alerts",
            payload={
                "encounter_id": encounter_id,
                "drug_name": drug_name,
                "flag": flag.value,
                "severity": severity,
                "agent": self.agent_name,
            },
        )
```

---

## Validation Steps

### Step 1: Category Assignment Smoke Test
```python
from app.agents.medication_reconciliation.agent import MedicationReconciliationAgent
from app.agents.medication_reconciliation.models import RawMedicationEntry
from app.models.medication import MedicationListSource, ReconciliationCategory

# Simulate _compare with known inputs
pre = [RawMedicationEntry(MedicationListSource.PRE_ADMIT, "stmt-1", "Metformin", "500 mg", "oral")]
dis = [RawMedicationEntry(MedicationListSource.DISCHARGE, "req-1", "Metformin", "500 mg", "oral")]

for e in pre + dis:
    e.rxnorm_cui = "860975"
    from app.agents.medication_reconciliation.dose_parser import parse_dose
    e.dose_value, e.dose_unit = parse_dose(e.dose_string)

raw_lists = {
    MedicationListSource.PRE_ADMIT: pre,
    MedicationListSource.INPATIENT: [],
    MedicationListSource.DISCHARGE: dis,
}

# Instantiate with mocks
from unittest.mock import AsyncMock, MagicMock
agent = MedicationReconciliationAgent(AsyncMock(), AsyncMock(), AsyncMock())
meds = agent._compare(raw_lists)
assert meds[0].reconciliation_category == ReconciliationCategory.CONTINUED
print("✓ CONTINUED category validated")
```

### Step 2: Duplicate Detection
```python
from app.agents.medication_reconciliation.agent import MedicationReconciliationAgent
from app.models.medication import Medication, MedicationListSource, ReconciliationFlag

agent = MedicationReconciliationAgent(None, None, None)

med1 = Medication(name="Metformin 500mg oral", rxnorm_cui="860975", route="oral",
                  sources=[MedicationListSource.DISCHARGE], flags=[])
med2 = Medication(name="Metformin XR 500mg oral", rxnorm_cui="860975", route="oral",
                  sources=[MedicationListSource.DISCHARGE], flags=[])

agent._detect_duplicates([med1, med2])
assert ReconciliationFlag.DUPLICATE in med1.flags
assert ReconciliationFlag.DUPLICATE in med2.flags
print("✓ DUPLICATE detection validated")
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Drug with no CUI falls back to name comparison — name mismatch misclassifies drug | High | High | Lowercased strip + partial match on name; log warning when CUI is None |
| Stop-order FHIR check times out — false `STOPPED_WITHOUT_ORDER` | Medium | Medium | `_check_stop_order` returns `False` on exception; alerts are informational, not blocking |
| Large medication list (>50 drugs) causes DB transaction timeout | Low | Medium | Batch `session.add` all records; single `commit` at end |
| `BaseAgent.publish_event` not yet implemented (US-024 dependency) | Medium | Medium | Stub `_publish_alert` with logger warning if Pub/Sub not configured |

---

## Definition of Done

- [ ] `MedicationReconciliationAgent` extends `BaseAgent`
- [ ] `run(encounter_id)` orchestrates fetch → normalise → compare → detect → alert → persist
- [ ] All four `ReconciliationCategory` values assigned correctly
- [ ] `DUPLICATE` flag detection working
- [ ] `STOPPED_WITHOUT_ORDER` flag detection working with FHIR stop-order check
- [ ] `PharmacistAlert` published to `pharmacist-alerts` Pub/Sub topic
- [ ] All `Medication` ORM records persisted to database
- [ ] Smoke tests pass locally
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-001:** ORM model and enums consumed here
- **TASK-002:** `FHIRMedicationFetcher` injected into agent
- **TASK-003:** `RxNormNormaliser` and `DoseParser` injected/called
- **TASK-005:** API endpoint reads persisted records written by this agent
- **TASK-006:** Unit tests validate this agent's logic

---

## Notes for Implementer

1. **`BaseAgent` interface** — Review US-024 for the exact `publish_event` signature; adjust `_publish_alert` accordingly.
2. **CUI fallback** — When `rxnorm_cui` is `None`, use `name.lower().strip()` as the comparison key. Warn in logs so clinicians can investigate.
3. **`DOSE_CHANGED` vs `CONTINUED`** — Only flag `DOSE_CHANGED` when both pre-admit and discharge parsed doses are non-`None` and differ. If either is `None`, default to `CONTINUED` to avoid false positives.
4. **Inpatient list** — Inpatient administrations are recorded in `sources` for audit but do not affect `CONTINUED`/`STOPPED`/`NEW` categorisation (which compares only pre-admit ↔ discharge per FR-030).

---

*Task created on 2026-07-16 for US-030 by plan-development-tasks workflow.*
