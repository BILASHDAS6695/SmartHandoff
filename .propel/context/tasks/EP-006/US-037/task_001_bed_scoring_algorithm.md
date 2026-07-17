---
id: TASK-001
title: "BedScoringAlgorithm — Scoring Engine and Configurable Weight YAML"
user_story: US-037
epic: EP-006
sprint: 2
layer: Backend / AI Agent
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-035/TASK-001, US-012]
---

# TASK-001: BedScoringAlgorithm — Scoring Engine and Configurable Weight YAML

> **Story:** US-037 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-037 requires a `BedScoringAlgorithm` class that scores each VACANT bed against an incoming patient's admission attributes. This task implements the complete scoring engine: four normalised factor functions (`acuity_match`, `care_type_match`, `isolation_match`, `gender_match`), a configurable weight YAML file at `config/bed_scoring_weights.yaml`, and hot-reload support so weights can be tuned without redeployment.

The scorer is a pure Python class (no external I/O) consumed by TASK-002's recommendation API. Factor functions return values in `[0.0, 1.0]`; the final score is the weighted sum. Isolation filtering is **hard-coded** — an isolation-required patient **never** receives a non-isolation bed regardless of weight configuration (AC Scenario 2).

**Design references:**
- US-037 AC Scenario 3 — weight formula: `score = Σ(weight_i × factor_i)`; weights sum to 1.0
- US-037 AC Scenario 2 — isolation-required patients: non-isolation beds → score 0, excluded from results
- US-037 Technical Notes — `config/bed_scoring_weights.yaml`; hot-reloadable; score range 0.0–1.0
- US-037 DoD — `BedScoringAlgorithm` class; 4 scoring factors each 0–1
- design.md §3.1 — Bed Management Agent responsibility; Scikit-learn + scoring

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | Isolation-required patient: non-isolation beds excluded (score=0, filtered) |
| Scenario 3 | Weighted score = `acuity×0.4 + care_type×0.35 + isolation×0.15 + gender×0.10`; weights configurable from YAML |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/bed_management/scoring
touch backend/app/agents/bed_management/scoring/__init__.py
touch backend/app/agents/bed_management/scoring/algorithm.py
touch backend/app/agents/bed_management/scoring/factors.py
touch backend/app/agents/bed_management/scoring/weight_loader.py
mkdir -p backend/config
touch backend/config/bed_scoring_weights.yaml
```

### 2. Create `backend/config/bed_scoring_weights.yaml`

```yaml
# Bed recommendation scoring weights — hot-reloadable without deployment.
# All weights must sum to 1.0.
# US-037 AC Scenario 3 defaults.
weights:
  acuity: 0.40
  care_type: 0.35
  isolation: 0.15
  gender: 0.10
```

### 3. Implement `backend/app/agents/bed_management/scoring/weight_loader.py`

```python
"""Hot-reloadable YAML weight loader for BedScoringAlgorithm.

Reads ``config/bed_scoring_weights.yaml`` on each call to ``load_weights()``.
No caching — caller may wrap with an LRU cache if performance requires it
(not needed at <5,000 ADT events/day; US-037 Technical Notes).

Design refs:
    US-037 Technical Notes — hot-reloadable without deployment
    US-037 AC Scenario 3   — configurable weights; sum must equal 1.0
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS_PATH = Path(__file__).parents[4] / "config" / "bed_scoring_weights.yaml"


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Immutable weight container for a single scoring run."""

    acuity: float
    care_type: float
    isolation: float
    gender: float

    def validate(self) -> None:
        """Raise ``ValueError`` if weights do not sum to 1.0 (±0.001 tolerance)."""
        total = self.acuity + self.care_type + self.isolation + self.gender
        if not (0.999 <= total <= 1.001):
            raise ValueError(
                f"Scoring weights must sum to 1.0; got {total:.4f}. "
                "Check config/bed_scoring_weights.yaml."
            )


def load_weights(path: Path | None = None) -> ScoringWeights:
    """Load and validate scoring weights from the YAML config file.

    Args:
        path: Override path for testing. Defaults to
              ``backend/config/bed_scoring_weights.yaml``.

    Returns:
        Validated :class:`ScoringWeights` instance.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If weights do not sum to 1.0.
        KeyError: If expected weight keys are missing from the YAML.
    """
    config_path = path or Path(
        os.environ.get("BED_SCORING_WEIGHTS_PATH", str(_DEFAULT_WEIGHTS_PATH))
    )
    logger.debug("Loading bed scoring weights from %s", config_path)
    with config_path.open() as fh:
        raw = yaml.safe_load(fh)

    w = raw["weights"]
    weights = ScoringWeights(
        acuity=float(w["acuity"]),
        care_type=float(w["care_type"]),
        isolation=float(w["isolation"]),
        gender=float(w["gender"]),
    )
    weights.validate()
    return weights
```

### 4. Implement `backend/app/agents/bed_management/scoring/factors.py`

```python
"""Individual scoring factor functions for bed recommendation.

Each function returns a normalised score in [0.0, 1.0]:
    1.0 — perfect match
    0.0 — no match (or hard exclusion for isolation)

Design refs:
    US-037 AC Scenario 2 — isolation: non-isolation bed → 0.0 (excluded by algorithm.py)
    US-037 AC Scenario 3 — each factor independently in 0–1 range
    US-037 DoD           — factors: acuity_match, care_type_match, isolation_match, gender_match
"""
from __future__ import annotations


def score_acuity_match(patient_acuity: str, bed_acuity_level: str) -> float:
    """Score how well the bed's acuity level meets the patient's need.

    Acuity hierarchy (descending capability):
        ICU > ICU-step-down > MED-SURG > OBS > ED

    A bed with higher capability than required scores 0.8 (over-resourced).
    An exact match scores 1.0.
    A bed with lower capability than required scores 0.0 (unsafe — hard fail).

    Args:
        patient_acuity: Patient's required acuity level string.
        bed_acuity_level: Bed's acuity capability string.

    Returns:
        Float in [0.0, 1.0].
    """
    _HIERARCHY: list[str] = ["OBS", "ED", "MED-SURG", "ICU-step-down", "ICU"]

    patient_idx = _HIERARCHY.index(patient_acuity) if patient_acuity in _HIERARCHY else -1
    bed_idx = _HIERARCHY.index(bed_acuity_level) if bed_acuity_level in _HIERARCHY else -1

    if patient_idx < 0 or bed_idx < 0:
        return 0.0  # unknown acuity — conservative default

    if bed_idx == patient_idx:
        return 1.0  # exact match
    if bed_idx > patient_idx:
        return 0.8  # over-resourced — acceptable but not optimal
    return 0.0  # under-resourced — unsafe, hard fail


def score_care_type_match(patient_care_type: str, bed_care_type: str) -> float:
    """Score care type compatibility.

    Exact match → 1.0; compatible (e.g. patient needs general, bed offers step-down) → 0.6;
    incompatible → 0.0.

    Args:
        patient_care_type: Admit care type from ``ADTEvent.admit_type`` (e.g. ``"CARDIAC"``).
        bed_care_type: Bed's designated care type from the bed record.

    Returns:
        Float in [0.0, 1.0].
    """
    if not patient_care_type or not bed_care_type:
        return 0.5  # unknown — neutral score

    patient_norm = patient_care_type.strip().upper()
    bed_norm = bed_care_type.strip().upper()

    if patient_norm == bed_norm:
        return 1.0

    # General-purpose beds are compatible with any care type
    if bed_norm in ("GENERAL", "MED-SURG"):
        return 0.6

    return 0.0


def score_isolation_match(
    patient_isolation_required: bool,
    bed_isolation_capable: bool,
) -> float:
    """Score isolation compatibility.

    Hard rules (AC Scenario 2):
        - Isolation required + isolation capable  → 1.0
        - Isolation required + NOT capable        → 0.0  (excluded by caller)
        - No isolation required + capable         → 0.8  (over-resourced)
        - No isolation required + not capable     → 1.0  (perfect fit)

    Args:
        patient_isolation_required: Whether patient needs isolation room.
        bed_isolation_capable: Whether the bed's room supports isolation.

    Returns:
        Float in [0.0, 1.0].
    """
    if patient_isolation_required and bed_isolation_capable:
        return 1.0
    if patient_isolation_required and not bed_isolation_capable:
        return 0.0  # hard exclusion — caller must filter this out
    if not patient_isolation_required and bed_isolation_capable:
        return 0.8  # wastes an isolation room, penalised
    return 1.0  # non-isolation patient in standard room — ideal


def score_gender_match(patient_gender: str, bed_gender_designation: str) -> float:
    """Score gender designation compatibility.

    Rules:
        - Exact match (``female`` / ``female``) → 1.0
        - Bed is ``any`` (gender-neutral)        → 0.8
        - Mismatch                               → 0.0

    Args:
        patient_gender: Patient gender string (``female``, ``male``, ``other``).
        bed_gender_designation: Bed designation (``female``, ``male``, ``any``).

    Returns:
        Float in [0.0, 1.0].
    """
    if not patient_gender or not bed_gender_designation:
        return 0.5  # unknown — neutral score

    patient_norm = patient_gender.strip().lower()
    bed_norm = bed_gender_designation.strip().lower()

    if bed_norm == "any":
        return 0.8  # gender-neutral bed — acceptable
    if patient_norm == bed_norm:
        return 1.0
    return 0.0  # gender mismatch
```

### 5. Implement `backend/app/agents/bed_management/scoring/algorithm.py`

```python
"""BedScoringAlgorithm — scores VACANT beds against a patient admission profile.

Consumes four factor functions and configurable weights loaded from YAML.
Isolation-required patients are hard-filtered: beds without isolation capability
receive score 0.0 and are excluded from results before ranking (AC Scenario 2).

Design refs:
    US-037 AC Scenario 1   — response contains ≥3 ranked beds with score_breakdown
    US-037 AC Scenario 2   — isolation patients: non-isolation beds excluded
    US-037 AC Scenario 3   — score = Σ(weight_i × factor_i); weights configurable
    US-037 Technical Notes — score range 0.0–1.0; sort descending; return top 5
    US-037 DoD             — BedScoringAlgorithm class; score_breakdown for transparency
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.bed_management.scoring.factors import (
    score_acuity_match,
    score_care_type_match,
    score_gender_match,
    score_isolation_match,
)
from app.agents.bed_management.scoring.weight_loader import ScoringWeights, load_weights

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PatientAdmissionProfile:
    """Minimal patient attributes required for bed scoring.

    Sourced from the ``ADTEvent`` record associated with the encounter.
    No PHI fields — uses coded values only (ACR Scenario 1 / AIR-021).
    """

    acuity_level: str          # e.g. "ICU-step-down"
    admit_type: str            # e.g. "CARDIAC"
    isolation_required: bool
    gender: str                # e.g. "female"


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Per-factor score breakdown for transparency (AC Scenario 1)."""

    acuity_match: float
    care_type_match: float
    isolation_match: float
    gender_match: float


@dataclass(frozen=True, slots=True)
class BedRecommendation:
    """A single ranked bed recommendation returned by the algorithm."""

    bed_id: str
    unit: str
    room: str
    bed_number: str
    score: float
    score_breakdown: ScoreBreakdown


@dataclass
class BedScoringAlgorithm:
    """Scores and ranks VACANT beds against a patient admission profile.

    Usage::

        algo = BedScoringAlgorithm()
        recommendations = algo.score_and_rank(profile, beds)

    Args:
        weights_path: Optional override for the YAML weights file (used in tests).
    """

    weights_path: Path | None = field(default=None, repr=False)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def score_and_rank(
        self,
        profile: PatientAdmissionProfile,
        beds: list[dict[str, Any]],
    ) -> list[BedRecommendation]:
        """Score all VACANT beds and return the top 5, ranked descending by score.

        Isolation filter: If ``profile.isolation_required`` is ``True``, any bed
        with ``isolation_capable=False`` is silently excluded before scoring
        (AC Scenario 2).

        Args:
            profile: Patient admission attributes for scoring.
            beds: List of bed dicts from ``mv_bed_board`` with keys:
                  ``bed_id``, ``unit``, ``room``, ``bed_number``, ``bed_type``,
                  ``isolation_capable``, ``gender_designation``.

        Returns:
            Up to 5 :class:`BedRecommendation` objects sorted highest score first.
        """
        weights: ScoringWeights = load_weights(self.weights_path)

        recommendations: list[BedRecommendation] = []

        for bed in beds:
            bed_isolation_capable: bool = bool(bed.get("isolation_capable", False))

            # Hard isolation filter — AC Scenario 2
            if profile.isolation_required and not bed_isolation_capable:
                logger.debug(
                    "Bed %s excluded: isolation required but bed not capable",
                    bed["bed_id"],
                )
                continue

            breakdown = self._compute_breakdown(profile, bed)
            score = self._weighted_score(breakdown, weights)

            recommendations.append(
                BedRecommendation(
                    bed_id=bed["bed_id"],
                    unit=bed["unit"],
                    room=bed["room"],
                    bed_number=bed["bed_number"],
                    score=round(score, 4),
                    score_breakdown=breakdown,
                )
            )

        recommendations.sort(key=lambda r: r.score, reverse=True)
        top_5 = recommendations[:5]
        logger.info(
            "Bed scoring complete: %d candidates → %d recommendations",
            len(beds),
            len(top_5),
        )
        return top_5

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _compute_breakdown(
        self,
        profile: PatientAdmissionProfile,
        bed: dict[str, Any],
    ) -> ScoreBreakdown:
        return ScoreBreakdown(
            acuity_match=score_acuity_match(profile.acuity_level, bed.get("bed_type", "")),
            care_type_match=score_care_type_match(
                profile.admit_type, bed.get("care_type", "")
            ),
            isolation_match=score_isolation_match(
                profile.isolation_required, bool(bed.get("isolation_capable", False))
            ),
            gender_match=score_gender_match(
                profile.gender, bed.get("gender_designation", "any")
            ),
        )

    @staticmethod
    def _weighted_score(breakdown: ScoreBreakdown, weights: ScoringWeights) -> float:
        return (
            weights.acuity * breakdown.acuity_match
            + weights.care_type * breakdown.care_type_match
            + weights.isolation * breakdown.isolation_match
            + weights.gender * breakdown.gender_match
        )
```

### 6. Export from `backend/app/agents/bed_management/scoring/__init__.py`

```python
from app.agents.bed_management.scoring.algorithm import (
    BedRecommendation,
    BedScoringAlgorithm,
    PatientAdmissionProfile,
    ScoreBreakdown,
)
from app.agents.bed_management.scoring.weight_loader import ScoringWeights, load_weights

__all__ = [
    "BedRecommendation",
    "BedScoringAlgorithm",
    "PatientAdmissionProfile",
    "ScoreBreakdown",
    "ScoringWeights",
    "load_weights",
]
```

---

## Validation Checklist

- [ ] `BedScoringAlgorithm.score_and_rank()` returns ≤5 results sorted descending by `score`
- [ ] Isolation-required patient + non-isolation bed → entry excluded (never appears in results)
- [ ] Score formula: `acuity×0.4 + care_type×0.35 + isolation×0.15 + gender×0.10` matches default YAML
- [ ] `ScoringWeights.validate()` raises `ValueError` if sum ≠ 1.0 (±0.001)
- [ ] `load_weights()` respects `BED_SCORING_WEIGHTS_PATH` env var override
- [ ] `score_breakdown` fields are each in `[0.0, 1.0]`
- [ ] No PHI in any log statements (encounter_id/bed_id only)
- [ ] `ruff check` and `bandit -ll` pass on all scoring module files

---

## Files Created

| File | Purpose |
|------|---------|
| `backend/config/bed_scoring_weights.yaml` | Default configurable weights (hot-reloadable) |
| `backend/app/agents/bed_management/scoring/__init__.py` | Package exports |
| `backend/app/agents/bed_management/scoring/weight_loader.py` | YAML loader + `ScoringWeights` dataclass |
| `backend/app/agents/bed_management/scoring/factors.py` | Four factor scoring functions |
| `backend/app/agents/bed_management/scoring/algorithm.py` | `BedScoringAlgorithm` orchestrator |
