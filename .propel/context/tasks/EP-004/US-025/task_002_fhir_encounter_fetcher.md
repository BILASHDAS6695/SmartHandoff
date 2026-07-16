---
id: TASK-002
title: "Implement FHIR Encounter Data Fetcher for Documentation Agent"
user_story: US-025
epic: EP-004
sprint: 2
layer: Backend — Integration
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-017]
---

# TASK-002: Implement FHIR Encounter Data Fetcher for Documentation Agent

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Integration | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `DocumentationAgent` must retrieve clinical context from the FHIR R4 API before rendering the Jinja2 prompt template. This task implements `FHIREncounterFetcher` — a focused data-access class that fetches `Patient`, `Encounter`, `Condition`, and `MedicationStatement` resources for a given encounter ID. The fetcher enforces PHI minimisation at the data layer: it strips direct identifiers from the returned context object so that the prompt template (TASK-003) never receives raw PII.

The `FHIRClient` HTTP client is already implemented by US-017. This task consumes that client, it does not re-implement it.

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 3** | Fetcher returns conditions (ICD-10), medications (RxNorm), and encounter context required for all six mandatory summary sections |
| **Scenario 4** | PHI stripping at fetcher level ensures `full_name`, `address`, `phone`, `ssn` never appear in the context object passed to the prompt template |

---

## Implementation Steps

### 1. Create `agents/documentation/fhir_fetcher.py`

```python
"""
FHIR encounter data fetcher for the Documentation Agent.

Fetches Patient, Encounter, Condition, and MedicationStatement resources
for a given encounter ID and returns a PHI-minimised EncounterContext
dataclass safe for inclusion in LLM prompt templates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from integrations.fhir_client import FHIRClient  # US-017 implementation

logger = logging.getLogger(__name__)


@dataclass
class DiagnosisContext:
    """PHI-safe diagnosis extracted from FHIR Condition resource."""
    icd10_code: str
    description: str
    is_primary: bool = False


@dataclass
class MedicationContext:
    """PHI-safe medication extracted from FHIR MedicationStatement resource."""
    drug_name: str
    dose: str
    frequency: str
    route: str
    rxnorm_code: Optional[str] = None


@dataclass
class EncounterContext:
    """
    PHI-minimised encounter context for LLM prompt rendering.

    DELIBERATELY EXCLUDES: patient_name, date_of_birth, address,
    phone_number, ssn, mrn. These fields must never appear here.

    Includes: encounter_id, admission_reason, diagnoses (ICD-10),
    medications, encounter_type, discharge_disposition.
    """
    encounter_id: str
    admission_reason: str
    encounter_type: str
    discharge_disposition: Optional[str]
    length_of_stay_days: Optional[int]
    diagnoses: List[DiagnosisContext] = field(default_factory=list)
    medications: List[MedicationContext] = field(default_factory=list)
    procedures_performed: List[str] = field(default_factory=list)


# PHI fields that must never propagate to the prompt layer
_PHI_FIELDS = frozenset({
    "family", "given", "text", "line", "city", "postalCode",
    "phone", "email", "birthDate", "identifier", "ssn",
})


class FHIREncounterFetcher:
    """
    Fetches and transforms FHIR encounter data into a PHI-minimised
    EncounterContext safe for LLM prompt rendering.

    Args:
        fhir_client: Async FHIR R4 HTTP client (injected; from US-017).
    """

    def __init__(self, fhir_client: FHIRClient) -> None:
        self._client = fhir_client

    async def fetch(self, encounter_id: str) -> EncounterContext:
        """
        Fetch Patient, Encounter, Condition, and MedicationStatement resources
        and return a PHI-minimised EncounterContext.

        Raises:
            FHIRResourceNotFoundError: If the Encounter resource does not exist.
            FHIRClientError: On HTTP or parsing failures.
        """
        logger.info("Fetching FHIR encounter context", extra={"encounter_id": encounter_id})

        encounter_resource, conditions, medications = await self._fetch_all(encounter_id)

        context = EncounterContext(
            encounter_id=encounter_id,
            admission_reason=self._extract_admission_reason(encounter_resource),
            encounter_type=self._extract_encounter_type(encounter_resource),
            discharge_disposition=self._extract_discharge_disposition(encounter_resource),
            length_of_stay_days=self._calculate_los(encounter_resource),
            diagnoses=self._map_conditions(conditions),
            medications=self._map_medications(medications),
            procedures_performed=self._extract_procedures(encounter_resource),
        )

        logger.debug(
            "FHIR context fetched — PHI stripped",
            extra={
                "encounter_id": encounter_id,
                "diagnosis_count": len(context.diagnoses),
                "medication_count": len(context.medications),
            },
        )
        return context

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    async def _fetch_all(self, encounter_id: str):
        """Parallel fetch of Encounter, Conditions, and MedicationStatements."""
        import asyncio

        encounter_task = asyncio.create_task(
            self._client.get_resource("Encounter", encounter_id)
        )
        conditions_task = asyncio.create_task(
            self._client.search("Condition", {"encounter": encounter_id})
        )
        medications_task = asyncio.create_task(
            self._client.search("MedicationStatement", {"encounter": encounter_id})
        )

        encounter_resource = await encounter_task
        conditions = (await conditions_task).get("entry", [])
        medications = (await medications_task).get("entry", [])

        return encounter_resource, conditions, medications

    def _extract_admission_reason(self, encounter: dict) -> str:
        reasons = encounter.get("reasonCode", [])
        if reasons:
            return reasons[0].get("text", "Not specified")
        return "Not specified"

    def _extract_encounter_type(self, encounter: dict) -> str:
        types = encounter.get("type", [])
        if types:
            return types[0].get("text", "inpatient")
        return "inpatient"

    def _extract_discharge_disposition(self, encounter: dict) -> Optional[str]:
        hospitalization = encounter.get("hospitalization", {})
        disposition = hospitalization.get("dischargeDisposition", {})
        return disposition.get("text")

    def _calculate_los(self, encounter: dict) -> Optional[int]:
        """Calculate length of stay in days from period start/end."""
        from datetime import datetime

        period = encounter.get("period", {})
        start_str = period.get("start")
        end_str = period.get("end")
        if not start_str or not end_str:
            return None
        try:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            return max(0, (end - start).days)
        except ValueError:
            logger.warning("Could not parse encounter period dates", extra={"encounter_id": "redacted"})
            return None

    def _map_conditions(self, entries: list) -> List[DiagnosisContext]:
        diagnoses: List[DiagnosisContext] = []
        for entry in entries:
            resource = entry.get("resource", {})
            codings = resource.get("code", {}).get("coding", [])
            is_primary = (
                resource.get("category", [{}])[0]
                .get("coding", [{}])[0]
                .get("code", "") == "encounter-diagnosis"
            )
            for coding in codings:
                if coding.get("system", "").startswith("http://hl7.org/fhir/sid/icd-10"):
                    diagnoses.append(
                        DiagnosisContext(
                            icd10_code=coding["code"],
                            description=coding.get("display", resource.get("code", {}).get("text", "Unknown")),
                            is_primary=is_primary and not any(d.is_primary for d in diagnoses),
                        )
                    )
                    break  # one ICD-10 entry per condition
        return diagnoses

    def _map_medications(self, entries: list) -> List[MedicationContext]:
        medications: List[MedicationContext] = []
        for entry in entries:
            resource = entry.get("resource", {})
            med_coding = (
                resource.get("medicationCodeableConcept", {}).get("coding", [{}])[0]
            )
            dosage = resource.get("dosage", [{}])[0] if resource.get("dosage") else {}
            dose_qty = dosage.get("doseAndRate", [{}])[0].get("doseQuantity", {})

            medications.append(
                MedicationContext(
                    drug_name=med_coding.get("display", "Unknown"),
                    dose=f"{dose_qty.get('value', '')} {dose_qty.get('unit', '')}".strip() or "As directed",
                    frequency=dosage.get("timing", {}).get("code", {}).get("text", "As directed"),
                    route=dosage.get("route", {}).get("text", "oral"),
                    rxnorm_code=med_coding.get("code") if med_coding.get("system", "").endswith("rxnorm") else None,
                )
            )
        return medications

    def _extract_procedures(self, encounter: dict) -> List[str]:
        """Extract procedure descriptions from Encounter.reasonReference texts."""
        procedures = []
        for ref in encounter.get("reasonReference", []):
            display = ref.get("display")
            if display:
                procedures.append(display)
        return procedures
```

### 2. Unit Tests — `tests/agents/documentation/test_fhir_fetcher.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from agents.documentation.fhir_fetcher import FHIREncounterFetcher, EncounterContext


MOCK_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "ENC-001",
    "type": [{"text": "inpatient"}],
    "reasonCode": [{"text": "Acute heart failure"}],
    "period": {"start": "2026-07-10T08:00:00Z", "end": "2026-07-14T10:00:00Z"},
    "hospitalization": {"dischargeDisposition": {"text": "Home"}},
}

MOCK_CONDITIONS = {
    "entry": [
        {
            "resource": {
                "code": {
                    "coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I50.9", "display": "Heart failure"}],
                    "text": "Heart failure",
                },
                "category": [{"coding": [{"code": "encounter-diagnosis"}]}],
            }
        }
    ]
}

MOCK_MEDICATIONS = {
    "entry": [
        {
            "resource": {
                "medicationCodeableConcept": {
                    "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "29046", "display": "lisinopril"}]
                },
                "dosage": [
                    {
                        "doseAndRate": [{"doseQuantity": {"value": 10, "unit": "mg"}}],
                        "timing": {"code": {"text": "once daily"}},
                        "route": {"text": "oral"},
                    }
                ],
            }
        }
    ]
}


@pytest.fixture
def mock_fhir_client():
    client = MagicMock()
    client.get_resource = AsyncMock(return_value=MOCK_ENCOUNTER)
    client.search = AsyncMock(side_effect=[MOCK_CONDITIONS, MOCK_MEDICATIONS])
    return client


@pytest.mark.asyncio
async def test_fetch_returns_encounter_context(mock_fhir_client):
    fetcher = FHIREncounterFetcher(mock_fhir_client)
    context = await fetcher.fetch("ENC-001")

    assert isinstance(context, EncounterContext)
    assert context.encounter_id == "ENC-001"
    assert len(context.diagnoses) == 1
    assert context.diagnoses[0].icd10_code == "I50.9"
    assert len(context.medications) == 1
    assert context.medications[0].drug_name == "lisinopril"


@pytest.mark.asyncio
async def test_context_contains_no_phi_fields(mock_fhir_client):
    """Verify EncounterContext dataclass has no direct PII fields."""
    fetcher = FHIREncounterFetcher(mock_fhir_client)
    context = await fetcher.fetch("ENC-001")

    phi_attrs = {"patient_name", "date_of_birth", "address", "phone", "ssn", "mrn"}
    context_fields = set(context.__dataclass_fields__.keys())
    assert phi_attrs.isdisjoint(context_fields), f"PHI fields found in context: {phi_attrs & context_fields}"


@pytest.mark.asyncio
async def test_calculate_los_returns_correct_days(mock_fhir_client):
    fetcher = FHIREncounterFetcher(mock_fhir_client)
    context = await fetcher.fetch("ENC-001")
    assert context.length_of_stay_days == 4
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/agents/documentation/fhir_fetcher.py` |
| **Create** | `backend/tests/agents/documentation/test_fhir_fetcher.py` |

---

## Definition of Done

- [ ] `FHIREncounterFetcher.fetch()` performs parallel async fetch of Encounter, Conditions, and MedicationStatements
- [ ] `EncounterContext` dataclass contains no PHI field names (`patient_name`, `dob`, `ssn`, `address`, `phone`)
- [ ] ICD-10 codes extracted from `Condition.code.coding` (system `hl7.org/fhir/sid/icd-10-cm`)
- [ ] RxNorm codes extracted from `MedicationStatement.medicationCodeableConcept.coding`
- [ ] Length-of-stay calculated from `Encounter.period.start/end`
- [ ] All 3 unit tests pass; PHI isolation test explicitly asserts no PHI field names

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-017 | Story | `FHIRClient` async HTTP client must be implemented; this task only consumes it |
| TASK-001 | Task | `DiagnosisContext`, `MedicationContext` align with `DischargeSummarySchema` sub-models |
