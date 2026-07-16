# TASK-002: FHIR Medication Fetcher — MedicationStatement, MedicationAdministration, MedicationRequest

> **Story:** US-030 | **Effort:** 8 hours | **Layer:** Backend — FHIR Integration  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement an async FHIR medication fetcher service that retrieves all three medication lists for an encounter: pre-admission (`MedicationStatement`), inpatient (`MedicationAdministration`), and discharge (`MedicationRequest`), and normalises each into a shared `RawMedicationEntry` intermediate model.

---

## Context

The three-way reconciliation algorithm (TASK-004) requires a clean, typed set of medication entries sourced from different FHIR resource types. Each resource type uses different field structures for drug name, dose, and route. This task abstracts those differences so TASK-003 (RxNorm normalisation) and TASK-004 (comparison) work against a uniform model.

**Upstream Dependencies:**
- US-017: FHIR client infrastructure (`FHIRClient`, async `httpx` session)
- TASK-001: `MedicationListSource` enum

---

## Scope

### In Scope

1. **`RawMedicationEntry` dataclass** — `backend/app/agents/medication_reconciliation/models.py`:
   - `source: MedicationListSource`
   - `fhir_id: str`
   - `name: str` — display text from FHIR
   - `dose_string: str | None` — raw dose string e.g. `"500 mg"`
   - `route: str | None`
   - `frequency: str | None`
   - `status: str | None` — FHIR status field (`active`, `stopped`, etc.)

2. **`FHIRMedicationFetcher` service** — `backend/app/agents/medication_reconciliation/fhir_fetcher.py`:
   - `fetch_pre_admit(encounter_id: str) -> list[RawMedicationEntry]` — queries `MedicationStatement?context={encounter_id}`
   - `fetch_inpatient(encounter_id: str) -> list[RawMedicationEntry]` — queries `MedicationAdministration?context={encounter_id}`
   - `fetch_discharge(encounter_id: str) -> list[RawMedicationEntry]` — queries `MedicationRequest?encounter={encounter_id}&status=active`
   - `fetch_all(encounter_id: str) -> dict[MedicationListSource, list[RawMedicationEntry]]` — calls all three concurrently via `asyncio.gather`

3. **FHIR response parsers** (private helpers in `fhir_fetcher.py`):
   - `_parse_medication_statement(resource: dict) -> RawMedicationEntry`
   - `_parse_medication_administration(resource: dict) -> RawMedicationEntry`
   - `_parse_medication_request(resource: dict) -> RawMedicationEntry`
   - `_extract_dose_string(dosage: list[dict]) -> str | None` — shared dose extractor

### Out of Scope

- RxNorm CUI lookup (TASK-003)
- Comparison algorithm (TASK-004)
- Database persistence (TASK-005)

---

## Acceptance Criteria

### AC1: `fetch_all` Returns All Three Lists
**Given** a valid encounter with medications in each FHIR list  
**When** `fetch_all(encounter_id)` is called  
**Then** the result dict contains keys `PRE_ADMIT`, `INPATIENT`, `DISCHARGE` each mapping to a non-empty list of `RawMedicationEntry`

### AC2: Concurrent Fetch
**Given** FHIR API latency of ~200ms per call  
**When** `fetch_all` is called  
**Then** all three FHIR calls execute concurrently (total wall time ≈ single call time, not 3×)

### AC3: FHIR `MedicationStatement` Parsed Correctly
**Given** a `MedicationStatement` FHIR resource with `medicationCodeableConcept.text = "Metformin 500mg oral"`  
**When** `_parse_medication_statement` is called  
**Then** `entry.name == "Metformin 500mg oral"` and `entry.source == MedicationListSource.PRE_ADMIT`

### AC4: FHIR `MedicationAdministration` Parsed Correctly
**Given** a `MedicationAdministration` resource  
**When** `_parse_medication_administration` is called  
**Then** `entry.source == MedicationListSource.INPATIENT` and dose/route are extracted if present

### AC5: `MedicationRequest` with `status=stopped` Preserved
**Given** a `MedicationRequest` with `status: "stopped"`  
**When** `_parse_medication_request` is called  
**Then** `entry.status == "stopped"` is set (used by TASK-004 for stop-order detection)

### AC6: Empty List on 404 / Empty Bundle
**Given** no `MedicationStatement` resources exist for the encounter  
**When** `fetch_pre_admit` is called  
**Then** returns `[]` without raising an exception

---

## Implementation Details

### File: `backend/app/agents/medication_reconciliation/models.py`

```python
"""Shared intermediate models for medication reconciliation."""

from dataclasses import dataclass, field
from app.models.medication import MedicationListSource


@dataclass
class RawMedicationEntry:
    """
    Normalised representation of a single medication from any FHIR list.
    Source-agnostic; used as input for RxNorm normalisation and comparison.
    """
    source: MedicationListSource
    fhir_id: str
    name: str
    dose_string: str | None = None  # e.g. "500 mg"
    route: str | None = None
    frequency: str | None = None
    status: str | None = None       # FHIR status: active, stopped, completed
```

### File: `backend/app/agents/medication_reconciliation/fhir_fetcher.py`

```python
"""FHIR medication list fetcher for three-way reconciliation."""

import asyncio
import logging
from app.core.fhir.client import FHIRClient
from app.models.medication import MedicationListSource
from .models import RawMedicationEntry

logger = logging.getLogger(__name__)


class FHIRMedicationFetcher:
    """
    Fetches pre-admission, inpatient, and discharge medication lists
    from FHIR R4 for a given encounter.
    """

    def __init__(self, fhir_client: FHIRClient) -> None:
        self._client = fhir_client

    async def fetch_all(
        self, encounter_id: str
    ) -> dict[MedicationListSource, list[RawMedicationEntry]]:
        """Concurrently fetch all three FHIR medication lists."""
        pre_admit, inpatient, discharge = await asyncio.gather(
            self.fetch_pre_admit(encounter_id),
            self.fetch_inpatient(encounter_id),
            self.fetch_discharge(encounter_id),
        )
        return {
            MedicationListSource.PRE_ADMIT: pre_admit,
            MedicationListSource.INPATIENT: inpatient,
            MedicationListSource.DISCHARGE: discharge,
        }

    async def fetch_pre_admit(self, encounter_id: str) -> list[RawMedicationEntry]:
        """Fetch MedicationStatement resources (pre-admission list)."""
        bundle = await self._client.search(
            "MedicationStatement", {"context": encounter_id}
        )
        return [
            self._parse_medication_statement(r)
            for r in self._extract_entries(bundle)
        ]

    async def fetch_inpatient(self, encounter_id: str) -> list[RawMedicationEntry]:
        """Fetch MedicationAdministration resources (inpatient list)."""
        bundle = await self._client.search(
            "MedicationAdministration", {"context": encounter_id}
        )
        return [
            self._parse_medication_administration(r)
            for r in self._extract_entries(bundle)
        ]

    async def fetch_discharge(self, encounter_id: str) -> list[RawMedicationEntry]:
        """Fetch MedicationRequest resources (discharge list)."""
        bundle = await self._client.search(
            "MedicationRequest",
            {"encounter": encounter_id},
        )
        return [
            self._parse_medication_request(r)
            for r in self._extract_entries(bundle)
        ]

    # ── Private parsers ───────────────────────────────────────────────

    def _parse_medication_statement(self, resource: dict) -> RawMedicationEntry:
        return RawMedicationEntry(
            source=MedicationListSource.PRE_ADMIT,
            fhir_id=resource.get("id", ""),
            name=self._extract_med_name(resource),
            dose_string=self._extract_dose_string(resource.get("dosage", [])),
            route=self._extract_route(resource.get("dosage", [])),
            frequency=self._extract_frequency(resource.get("dosage", [])),
            status=resource.get("status"),
        )

    def _parse_medication_administration(self, resource: dict) -> RawMedicationEntry:
        dosage = [resource.get("dosage", {})]
        return RawMedicationEntry(
            source=MedicationListSource.INPATIENT,
            fhir_id=resource.get("id", ""),
            name=self._extract_med_name(resource),
            dose_string=self._extract_dose_string(dosage),
            route=self._extract_route(dosage),
            status=resource.get("status"),
        )

    def _parse_medication_request(self, resource: dict) -> RawMedicationEntry:
        return RawMedicationEntry(
            source=MedicationListSource.DISCHARGE,
            fhir_id=resource.get("id", ""),
            name=self._extract_med_name(resource),
            dose_string=self._extract_dose_string(
                resource.get("dosageInstruction", [])
            ),
            route=self._extract_route(resource.get("dosageInstruction", [])),
            frequency=self._extract_frequency(
                resource.get("dosageInstruction", [])
            ),
            status=resource.get("status"),
        )

    def _extract_med_name(self, resource: dict) -> str:
        """Extract display name from medicationCodeableConcept or medicationReference."""
        concept = resource.get("medicationCodeableConcept", {})
        if text := concept.get("text"):
            return text
        codings = concept.get("coding", [])
        if codings:
            return codings[0].get("display", "Unknown")
        ref = resource.get("medicationReference", {})
        return ref.get("display", "Unknown")

    def _extract_dose_string(self, dosage_list: list[dict]) -> str | None:
        """Extract first dose quantity text from dosage instructions."""
        for d in dosage_list:
            dose = d.get("doseAndRate", [{}])
            if dose:
                qty = dose[0].get("doseQuantity", {})
                value = qty.get("value")
                unit = qty.get("unit", "")
                if value is not None:
                    return f"{value} {unit}".strip()
        return None

    def _extract_route(self, dosage_list: list[dict]) -> str | None:
        for d in dosage_list:
            route = d.get("route", {})
            if text := route.get("text"):
                return text
            codings = route.get("coding", [])
            if codings:
                return codings[0].get("display")
        return None

    def _extract_frequency(self, dosage_list: list[dict]) -> str | None:
        for d in dosage_list:
            timing = d.get("timing", {})
            if code := timing.get("code", {}).get("text"):
                return code
        return None

    @staticmethod
    def _extract_entries(bundle: dict) -> list[dict]:
        """Safely extract resource entries from a FHIR Bundle."""
        return [
            entry["resource"]
            for entry in bundle.get("entry", [])
            if "resource" in entry
        ]
```

---

## Validation Steps

### Step 1: Concurrent Fetch Timing
```python
import asyncio, time
from unittest.mock import AsyncMock, patch
from app.agents.medication_reconciliation.fhir_fetcher import FHIRMedicationFetcher

async def test_concurrency():
    mock_client = AsyncMock()
    # Simulate 200ms FHIR latency
    async def slow_search(*args, **kwargs):
        await asyncio.sleep(0.2)
        return {"entry": []}
    mock_client.search.side_effect = slow_search

    fetcher = FHIRMedicationFetcher(mock_client)
    start = time.monotonic()
    result = await fetcher.fetch_all("enc-123")
    elapsed = time.monotonic() - start

    assert elapsed < 0.4, f"Expected ~0.2s, got {elapsed:.2f}s — not concurrent!"
    print(f"✓ Concurrent fetch in {elapsed:.2f}s")

asyncio.run(test_concurrency())
```

### Step 2: Parser Smoke Test
```python
from app.agents.medication_reconciliation.fhir_fetcher import FHIRMedicationFetcher
from unittest.mock import AsyncMock

fetcher = FHIRMedicationFetcher(AsyncMock())

sample_statement = {
    "id": "stmt-001",
    "status": "active",
    "medicationCodeableConcept": {"text": "Metformin 500mg"},
    "dosage": [{"doseAndRate": [{"doseQuantity": {"value": 500, "unit": "mg"}}],
                "route": {"text": "oral"}}],
}
entry = fetcher._parse_medication_statement(sample_statement)
assert entry.name == "Metformin 500mg"
assert entry.dose_string == "500 mg"
assert entry.route == "oral"
print("✓ MedicationStatement parsed correctly")
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| FHIR server returns medication name in `coding[0].display` not `text` | High | Medium | Implement fallback chain in `_extract_med_name` (text → coding.display → ref.display) |
| `MedicationAdministration` uses single `dosage` object not array | High | Low | Wrap in list `[resource.get("dosage", {})]` before passing to shared extractor |
| FHIR Bundle pagination (>50 results) | Medium | Medium | Check `Bundle.link[rel=next]` and paginate; use US-017 FHIR client paginator if available |
| Encounter 404 on FHIR server | Medium | Low | Return empty list; log warning; agent proceeds with partial data |

---

## Definition of Done

- [ ] `RawMedicationEntry` dataclass defined in `models.py`
- [ ] `FHIRMedicationFetcher` class with `fetch_all`, `fetch_pre_admit`, `fetch_inpatient`, `fetch_discharge`
- [ ] All three FHIR resource types parsed to `RawMedicationEntry`
- [ ] Concurrent fetch via `asyncio.gather` verified
- [ ] Empty bundle returns `[]` without exception
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-001:** Enums (`MedicationListSource`) consumed here
- **TASK-003:** RxNorm normalisation receives `RawMedicationEntry.name`
- **TASK-004:** Reconciliation agent calls `FHIRMedicationFetcher.fetch_all`

---

## Notes for Implementer

1. **FHIR Client injection** — Inject `FHIRClient` via constructor; never instantiate inside the fetcher to keep it testable.
2. **`MedicationAdministration` vs `MedicationStatement`** — The former records actual drug given (inpatient); the latter records a drug that the patient *reports* taking (pre-admit). Keep sources distinct.
3. **`status=stopped` filtering** — Do NOT filter out stopped `MedicationRequest`s; they are needed by TASK-004 to detect documented stop orders.
4. **Pagination** — For hospitals with high-volume inpatient administrations, bundle may be paginated. Implement `_follow_next_link` if >100 entries per call.

---

*Task created on 2026-07-16 for US-030 by plan-development-tasks workflow.*
