---
id: TASK-002
title: "HighRiskDrugClassDetector Service — Discharge List Scanner"
user_story: US-032
epic: EP-005
sprint: 2
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-032/TASK-001]
---

# TASK-002: HighRiskDrugClassDetector Service — Discharge List Scanner

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements the `HighRiskDrugClassDetector` class that:

1. Accepts a discharge medication list (as `list[DischargedMedication]` from US-030).
2. Strips dose/strength tokens from each drug name before matching.
3. Performs a case-insensitive lookup against `HighRiskDrugConfig.drug_to_class` (TASK-001).
4. Returns a list of `HighRiskDrugMatch` results — one per matched medication.

Per US-032 Technical Notes, detection is **additive**: a drug may simultaneously trigger both a drug-interaction alert (US-031) and a high-risk drug class alert (US-032). The detector itself has no knowledge of existing alerts; it returns matches unconditionally and lets the orchestrating pipeline (TASK-007) decide deduplication.

**Design references:**
- US-032 Technical Notes — case-insensitive name match; ADDITIVE with interaction alerts
- US-032 AC Scenario 1 — `Warfarin 5mg` on discharge list → `drug_class=ANTICOAGULANT`
- design.md §3.1 — Medication Reconciliation Agent (Cloud Run, LangChain)
- US-030 — `DischargedMedication` model with `drug_name` (RxNorm preferred name)

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 1** | Warfarin 5mg detected → `drug_class=ANTICOAGULANT`, `severity=HIGH`, `drug_name=Warfarin` |
| **DoD** | `HighRiskDrugClassDetector` class with configurable high-risk drug classes (YAML) |

---

## Implementation Steps

### 1. Create `backend/app/agents/medication_reconciliation/high_risk/detector.py`

```python
"""HighRiskDrugClassDetector — scans discharge medication list for ISMP high-alert drugs.

For each medication in the discharge list, performs a case-insensitive exact-match
against the pre-built drug_to_class reverse lookup from HighRiskDrugConfig.
Dose and strength tokens (e.g. "5mg", "10 units") are stripped before matching.

Detection is ADDITIVE: a drug can trigger both a drug-interaction alert (US-031)
and a high-risk drug class alert (US-032) simultaneously.

Design refs:
    US-032 AC Scenario 1   — Warfarin 5mg → ANTICOAGULANT, severity=HIGH
    US-032 Technical Notes — case-insensitive match; ADDITIVE with interaction alerts
    design.md §3.1         — Medication Reconciliation Agent
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.agents.medication_reconciliation.drug_interaction.checker import (
    DischargedMedication,
)
from app.agents.medication_reconciliation.high_risk.config_loader import (
    HighRiskDrugConfig,
    high_risk_drug_config as _default_config,
)

logger = logging.getLogger(__name__)

# Tokens that represent dose/strength/form information.
# Pattern: optional space + digit(s) + optional unit suffix.
_DOSE_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"\s+\d[\d.,]*\s*(?:mg|mcg|g|ml|units?|iu|meq|mmol|%|patch|tab|cap|sr|er|xr|ir)?\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class HighRiskDrugMatch:
    """A single high-risk drug detection result.

    Attributes:
        drug_name: Original drug name from the discharge list (unnormalised).
        normalised_name: Lower-cased, dose-stripped name used for matching.
        drug_class: ISMP high-risk class (ANTICOAGULANT | INSULIN | OPIOID | CHEMOTHERAPY).
        severity: Always HIGH per US-032 AC Scenario 1 and ISMP mandate.
    """

    drug_name: str
    normalised_name: str
    drug_class: str
    severity: str = "HIGH"


class HighRiskDrugClassDetector:
    """Scans a discharge medication list and identifies ISMP high-alert medications.

    Args:
        config: Optional custom :class:`HighRiskDrugConfig` instance.
                Defaults to the module-level singleton loaded from
                ``config/high_risk_drugs.yaml``.

    Example::

        detector = HighRiskDrugClassDetector()
        matches = detector.detect([DischargedMedication(rxcui="11289", drug_name="Warfarin 5mg")])
        # matches[0].drug_class == "ANTICOAGULANT"
        # matches[0].severity  == "HIGH"
    """

    def __init__(self, config: HighRiskDrugConfig | None = None) -> None:
        self._config: HighRiskDrugConfig = config or _default_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, medications: list[DischargedMedication]) -> list[HighRiskDrugMatch]:
        """Identify high-risk medications from a discharge list.

        Args:
            medications: List of discharged medications from US-030 normalisation.

        Returns:
            List of :class:`HighRiskDrugMatch` — one entry per matched drug.
            Empty list if no high-risk drugs found.
        """
        matches: list[HighRiskDrugMatch] = []
        for med in medications:
            match = self._check_medication(med)
            if match:
                logger.info(
                    "High-risk drug detected: drug_name=%r class=%s",
                    med.drug_name,
                    match.drug_class,
                )
                matches.append(match)
        return matches

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_medication(
        self, med: DischargedMedication
    ) -> HighRiskDrugMatch | None:
        """Check a single medication against the YAML lookup table.

        Returns:
            :class:`HighRiskDrugMatch` if matched, otherwise ``None``.
        """
        normalised = self._normalise(med.drug_name)
        drug_class = self._config.drug_to_class.get(normalised)
        if drug_class is None:
            return None
        return HighRiskDrugMatch(
            drug_name=med.drug_name,
            normalised_name=normalised,
            drug_class=drug_class,
            severity="HIGH",
        )

    @staticmethod
    def _normalise(drug_name: str) -> str:
        """Strip dose/strength tokens and lower-case the drug name.

        Args:
            drug_name: Raw drug name from discharge list (e.g. ``"Warfarin 5mg"``).

        Returns:
            Lower-cased, dose-stripped name (e.g. ``"warfarin"``).
        """
        stripped = _DOSE_TOKEN_PATTERN.sub("", drug_name)
        return stripped.strip().lower()
```

---

## Validation

- [ ] `HighRiskDrugClassDetector().detect([DischargedMedication(rxcui="11289", drug_name="Warfarin 5mg")])` returns one match with `drug_class="ANTICOAGULANT"` and `severity="HIGH"`
- [ ] `detect([DischargedMedication(rxcui="123", drug_name="Amoxicillin 500mg")])` returns empty list
- [ ] `_normalise("Insulin Glargine 100 Units/mL")` returns `"insulin glargine"`
- [ ] `_normalise("OxyCODONE 10mg ER")` returns `"oxycodone"` (case-insensitive)
- [ ] A medication list with both `Warfarin 5mg` and `Oxycodone 10mg` returns two matches (different classes)
- [ ] Custom `HighRiskDrugConfig` instance injected via constructor — default singleton not mutated

---

## Files Changed

| Action | Path |
|--------|------|
| Create | `backend/app/agents/medication_reconciliation/high_risk/detector.py` |
