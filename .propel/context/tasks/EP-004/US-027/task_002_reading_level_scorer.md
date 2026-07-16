---
id: TASK-002
title: "Implement `ReadingLevelScorer` — Flesch-Kincaid Grade Check with Simplification Retry"
user_story: US-027
epic: EP-004
sprint: 2
layer: Backend — AI Agent
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001]
---

# TASK-002: Implement `ReadingLevelScorer` — Flesch-Kincaid Grade Check with Simplification Retry

> **Story:** US-027 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI Agent | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-027 Scenario 1 mandates that English patient instructions score ≤6.0 on the Flesch-Kincaid Grade scale. The `ReadingLevelScorer` encapsulates:
1. Computing the FK grade for a given text block via the `textstat` library
2. Deciding whether simplification is needed (grade > 6.0)
3. Building the Gemini re-prompt payload: `"Rewrite the following at a 6th-grade reading level: {text}"`

The scorer is intentionally stateless and injected into `PatientInstructionsGenerator` (TASK-003). Retry logic (max 2 attempts) is handled at the generator level.

---

## Acceptance Criteria Addressed

| US-027 AC | Requirement |
|---|---|
| **Scenario 1** | Flesch-Kincaid Grade ≤ 6.0 verified via `textstat.flesch_kincaid_grade()` |
| **Scenario 1** | Plain language; avoid jargon enforced by re-prompt on grade > 6 |

---

## Implementation Steps

### 1. Create `agents/documentation/reading_level_scorer.py`

```python
"""
ReadingLevelScorer — Flesch-Kincaid Grade scoring for patient instructions.

Uses the `textstat` library to compute Flesch-Kincaid Grade Level for each
section of patient instructions. Provides the simplification re-prompt string
when the grade exceeds the target threshold.

Target: FK Grade ≤ 6.0 (US-027 Scenario 1, FR-021).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import textstat

logger = logging.getLogger(__name__)

# Maximum allowed Flesch-Kincaid Grade Level
FK_GRADE_TARGET: float = 6.0

# Simplification re-prompt template (Technical Notes, US-027)
_SIMPLIFY_PROMPT_TEMPLATE = (
    "Rewrite the following text so that a 6th-grade student can understand it. "
    "Use short sentences (under 15 words), everyday words, and no medical jargon. "
    "Keep all the important health information.\n\nText to rewrite:\n{text}"
)


@dataclass(frozen=True)
class ScoringResult:
    """Result of FK grade scoring for a single text block."""
    text: str
    grade: float
    passes: bool  # True when grade <= FK_GRADE_TARGET


class ReadingLevelScorer:
    """
    Flesch-Kincaid Grade scorer for patient instruction text.

    Stateless — safe to instantiate once and share across requests.
    """

    def score(self, text: str) -> ScoringResult:
        """
        Compute the Flesch-Kincaid Grade Level for `text`.

        Args:
            text: Plain-text content to evaluate. HTML/markdown must be stripped before calling.

        Returns:
            ScoringResult with the grade and pass/fail flag.
        """
        grade = textstat.flesch_kincaid_grade(text)
        passes = grade <= FK_GRADE_TARGET
        if not passes:
            logger.info(
                "FK Grade %.2f exceeds target %.1f — simplification required.",
                grade,
                FK_GRADE_TARGET,
            )
        return ScoringResult(text=text, grade=grade, passes=passes)

    def score_all_sections(self, sections: dict[str, str]) -> dict[str, ScoringResult]:
        """
        Score multiple text sections.

        Args:
            sections: Mapping of section_name → text.

        Returns:
            Mapping of section_name → ScoringResult.
        """
        return {name: self.score(text) for name, text in sections.items()}

    def aggregate_grade(self, sections: dict[str, str]) -> float:
        """
        Compute an aggregate FK grade as the average across all sections.

        Used to produce the single `primary_flesch_kincaid_grade` field stored
        in `PatientInstructionsDocument`.

        Args:
            sections: Mapping of section_name → text.

        Returns:
            Float mean of per-section FK grades. Returns 0.0 for empty input.
        """
        if not sections:
            return 0.0
        grades = [textstat.flesch_kincaid_grade(text) for text in sections.values()]
        return sum(grades) / len(grades)

    @staticmethod
    def build_simplify_prompt(text: str) -> str:
        """
        Build the Gemini simplification re-prompt for text that exceeds the grade target.

        Args:
            text: The original text that scored above FK_GRADE_TARGET.

        Returns:
            Formatted re-prompt string ready to send to Gemini Flash.
        """
        return _SIMPLIFY_PROMPT_TEMPLATE.format(text=text)
```

### 2. Add `textstat` to backend requirements

Add to `backend/requirements.txt` (or `pyproject.toml` dependencies):

```
textstat>=0.7.3
```

---

## File Locations

| File | Path |
|---|---|
| `reading_level_scorer.py` | `backend/agents/documentation/reading_level_scorer.py` |

---

## Validation Checklist

- [ ] `ReadingLevelScorer().score("The quick brown fox jumps over the lazy dog.")` returns `ScoringResult` with `grade` as float
- [ ] `ScoringResult.passes` is `True` when grade ≤ 6.0, `False` otherwise
- [ ] `aggregate_grade({})` returns `0.0` without raising
- [ ] `build_simplify_prompt("some text")` contains the substring `"6th-grade"`
- [ ] `textstat` added to `requirements.txt`
- [ ] Module has no side effects on import

---

## Dependencies

| Dependency | Notes |
|---|---|
| `textstat>=0.7.3` | Pure-Python; no system dependencies |
| `TASK-001` | `FK_GRADE_TARGET` feeds into `PatientInstructionsDocument.primary_flesch_kincaid_grade` |
