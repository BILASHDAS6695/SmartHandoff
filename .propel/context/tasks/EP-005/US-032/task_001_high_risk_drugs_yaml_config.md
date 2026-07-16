---
id: TASK-001
title: "Create `config/high_risk_drugs.yaml` — High-Risk Drug Class Mapping"
user_story: US-032
epic: EP-005
sprint: 2
layer: Backend / Config
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-030/TASK-003]
---

# TASK-001: Create `config/high_risk_drugs.yaml` — High-Risk Drug Class Mapping

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend / Config | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-032 requires a configurable YAML lookup table mapping high-risk drug classes to their canonical drug names. The `HighRiskDrugClassDetector` (TASK-002) loads this file at startup and performs case-insensitive name matching against the RxNorm preferred name produced by the US-030 normalisation service.

ISMP designates four mandatory high-alert medication classes:
- `ANTICOAGULANT` — warfarin, heparin, enoxaparin, rivaroxaban, apixaban, dabigatran
- `INSULIN` — insulin glargine, insulin aspart, insulin lispro, insulin NPH, insulin detemir
- `OPIOID` — oxycodone, hydrocodone, morphine, fentanyl, oxymorphone, hydromorphone, codeine
- `CHEMOTHERAPY` — methotrexate, cyclophosphamide, vincristine, doxorubicin, paclitaxel

The list must be extensible: adding a new class or drug name requires only a YAML edit and re-deploy — no code changes.

**Design references:**
- US-032 Technical Notes — YAML config; case-insensitive name match against RxNorm preferred name
- US-032 DoD — `config/high_risk_drugs.yaml`; classes `ANTICOAGULANT`, `INSULIN`, `OPIOID`, `CHEMOTHERAPY`
- design.md §3.1 — Medication Reconciliation Agent (Cloud Run, LangChain)

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 1** | `Warfarin` matched to `ANTICOAGULANT` class via YAML lookup |
| **DoD** | High-risk classes file present; extensible list requirement satisfied |

---

## Implementation Steps

### 1. Create `backend/config/high_risk_drugs.yaml`

Create the file at `backend/config/high_risk_drugs.yaml` with the content below.

> **Maintenance note:** Drug names are matched case-insensitively against the RxNorm preferred name returned by the US-030 normalisation service. When adding new entries, use the RxNorm preferred display name (all lower-case accepted). Do not add salts, strengths, or formulations — the matcher strips dose information before comparison.

```yaml
# SmartHandoff High-Risk Drug Class Configuration
#
# Source of truth for mandatory pharmacist alert detection (US-032, BR-002, BR-005).
# Loaded at application startup by HighRiskDrugClassDetector.
# Changes require a re-deploy of the Medication Reconciliation Agent Cloud Run service.
#
# ISMP High-Alert Medication classes (https://www.ismp.org/recommendations/high-alert-medications-community-ambulatory-care):
#   ANTICOAGULANT, INSULIN, OPIOID, CHEMOTHERAPY
#
# Matching rules:
#   - Case-insensitive exact match against RxNorm preferred name (stripped of dose/strength).
#   - A single drug may map to at most one class.
#   - Unknown/unmapped drugs are silently skipped — no alert raised.
#
# Design ref: US-032 Technical Notes, design.md §3.1

high_risk_drug_classes:

  ANTICOAGULANT:
    - warfarin
    - heparin
    - enoxaparin
    - rivaroxaban
    - apixaban
    - dabigatran
    - fondaparinux
    - argatroban
    - bivalirudin

  INSULIN:
    - insulin glargine
    - insulin aspart
    - insulin lispro
    - insulin nph
    - insulin detemir
    - insulin degludec
    - insulin regular
    - insulin 70/30
    - insulin 75/25

  OPIOID:
    - oxycodone
    - hydrocodone
    - morphine
    - fentanyl
    - oxymorphone
    - hydromorphone
    - codeine
    - tramadol
    - methadone
    - buprenorphine
    - tapentadol
    - meperidine

  CHEMOTHERAPY:
    - methotrexate
    - cyclophosphamide
    - vincristine
    - doxorubicin
    - paclitaxel
    - docetaxel
    - cisplatin
    - carboplatin
    - etoposide
    - fluorouracil
    - capecitabine
    - imatinib
```

### 2. Add schema validation helper `backend/app/agents/medication_reconciliation/high_risk/config_loader.py`

```python
"""Loader and validator for high_risk_drugs.yaml configuration.

Reads the YAML config at startup and exposes a pre-built reverse lookup dict
for O(1) drug-name → class resolution.

Design refs:
    US-032 Technical Notes — case-insensitive name match; YAML config
    US-032 DoD             — extensible list; config/high_risk_drugs.yaml
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).parents[5] / "config" / "high_risk_drugs.yaml"
)


class HighRiskDrugConfig:
    """Parsed and validated high-risk drug class configuration.

    Attributes:
        class_to_drugs: Mapping of drug-class name → set of lower-cased drug names.
        drug_to_class: Reverse mapping of lower-cased drug name → drug-class name.
    """

    def __init__(self, config_path: Path = _DEFAULT_CONFIG_PATH) -> None:
        self._path = config_path
        self.class_to_drugs: dict[str, set[str]] = {}
        self.drug_to_class: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Parse YAML, build reverse lookup, and validate no duplicate drug names."""
        if not self._path.exists():
            raise FileNotFoundError(
                f"High-risk drug config not found: {self._path}. "
                "Ensure config/high_risk_drugs.yaml is present in the container."
            )

        with self._path.open("r", encoding="utf-8") as fh:
            raw: dict = yaml.safe_load(fh)

        classes: dict[str, list[str]] = raw.get("high_risk_drug_classes", {})
        if not classes:
            raise ValueError(
                "high_risk_drugs.yaml: 'high_risk_drug_classes' key is empty or missing."
            )

        seen: dict[str, str] = {}
        for drug_class, drug_names in classes.items():
            normalised = {name.strip().lower() for name in drug_names}
            duplicates = normalised & set(seen)
            if duplicates:
                raise ValueError(
                    f"Duplicate drug names across classes: {duplicates}. "
                    f"Each drug must map to exactly one class."
                )
            for drug_name in normalised:
                seen[drug_name] = drug_class
            self.class_to_drugs[drug_class] = normalised

        self.drug_to_class = seen
        logger.info(
            "HighRiskDrugConfig loaded: %d classes, %d drugs",
            len(self.class_to_drugs),
            len(self.drug_to_class),
        )


# Module-level singleton loaded once at import time.
# Override in tests by patching `high_risk_drug_config` in this module.
high_risk_drug_config = HighRiskDrugConfig()
```

---

## Validation

- [ ] `backend/config/high_risk_drugs.yaml` exists and is valid YAML (`yaml.safe_load` succeeds without error)
- [ ] All four mandatory ISMP classes present: `ANTICOAGULANT`, `INSULIN`, `OPIOID`, `CHEMOTHERAPY`
- [ ] `HighRiskDrugConfig()` initialises without errors in a local Python shell
- [ ] `high_risk_drug_config.drug_to_class["warfarin"] == "ANTICOAGULANT"` passes
- [ ] `high_risk_drug_config.drug_to_class["oxycodone"] == "OPIOID"` passes
- [ ] Duplicate drug name across two classes raises `ValueError` on startup

---

## Files Changed

| Action | Path |
|--------|------|
| Create | `backend/config/high_risk_drugs.yaml` |
| Create | `backend/app/agents/medication_reconciliation/high_risk/config_loader.py` |
| Create | `backend/app/agents/medication_reconciliation/high_risk/__init__.py` |
