---
id: TASK-002
title: "UrgencyDetector Phase 1 — Keyword Pattern Matching (<10ms)"
user_story: US-044
epic: EP-008
sprint: 2
layer: Backend / AI Agent
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-044/TASK-001]
---

# TASK-002: UrgencyDetector Phase 1 — Keyword Pattern Matching (<10ms)

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

Phase 1 of the urgency detector must run **before** any LLM invocation (US-044 DoD). It uses compiled regex patterns from `config/urgency_keywords.yaml` (loaded in TASK-001) to scan the patient message in O(n) string operations. The target latency is <10ms, making it suitable for synchronous execution inside the request path.

If Phase 1 detects a keyword match, Phase 2 (Gemini semantic classification) is **skipped entirely** — the urgency verdict is immediate. Only when Phase 1 finds no match does execution proceed to Phase 2 (TASK-003).

**Design references:**
- design.md §3.1 — Patient Communication Agent: urgency detection, escalation routing
- US-044 Technical Notes — Phase 1: fast regex keyword match (O(n) string scan, <10ms)
- US-044 AC Scenario 2 — keyword list: "chest pain", "can't breathe", "severe bleeding", "unconscious", "stroke", "suicide"
- US-044 DoD — urgency detection runs BEFORE LLM call
- US-044 DoD — `UrgencyDetector` class: phase 1 keyword pattern matching, phase 2 Gemini semantic classification

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Keyword match produces `UrgencyDetectionResult.is_urgent=True` in <10ms |
| Scenario 2 | All six AC Scenario 2 keywords trigger `is_urgent=True` via Phase 1 |
| Scenario 4 | Non-urgent message "when should I take my metformin?" returns `is_urgent=False` |

---

## Implementation Steps

### 1. Create Phase 1 keyword matcher module

```bash
touch backend/app/agents/patient_comm/urgency/keyword_matcher.py
```

### 2. Implement `backend/app/agents/patient_comm/urgency/keyword_matcher.py`

```python
"""Phase 1 urgency detection: keyword pattern matching (US-044, TASK-002).

Performs an O(n) scan of the patient message against compiled regex patterns
loaded from config/urgency_keywords.yaml. Target latency: <10ms per message.

Design ref:
    US-044 Technical Notes — Phase 1: fast regex keyword match (O(n), <10ms)
    US-044 AC Scenario 2 — configurable keyword list
    US-044 DoD — keyword detection runs BEFORE any LLM call
"""
from __future__ import annotations

import logging
import re
import time

from backend.app.agents.patient_comm.urgency.config_loader import load_urgency_keywords
from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    UrgencyDetectionResult,
)

logger = logging.getLogger(__name__)


def detect_urgency_keyword(patient_message: str) -> UrgencyDetectionResult:
    """Run Phase 1 keyword scan against the patient message.

    Args:
        patient_message: Raw message text from the patient's chat input.
            Must be the original message text — no pre-processing or truncation.

    Returns:
        UrgencyDetectionResult with:
            - is_urgent=True, detection_phase=KEYWORD if a phrase matches
            - is_urgent=False, detection_phase=NONE if no keyword found
              (caller should proceed to Phase 2 Gemini classification)

    Security note:
        This function does NOT log the patient_message content — only the
        matched keyword phrase and elapsed time are logged.
        The raw message may contain PHI (diagnosis, symptoms) and must
        never appear in Cloud Logging output.
    """
    patterns: list[re.Pattern[str]] = load_urgency_keywords()

    t_start = time.perf_counter()
    matched: str | None = None

    for pattern in patterns:
        if pattern.search(patient_message):
            matched = pattern.pattern
            break

    elapsed_ms = (time.perf_counter() - t_start) * 1_000

    if matched:
        # Build a safe, non-PHI summary from the matched keyword only.
        # The raw patient message MUST NOT appear in the summary.
        summary = f"Urgency keyword detected: '{_extract_phrase(matched)}'"[:100]

        logger.info(
            "urgency_keyword_detected",
            extra={
                "matched_phrase": _extract_phrase(matched),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

        return UrgencyDetectionResult(
            is_urgent=True,
            detection_phase=DetectionPhase.KEYWORD,
            matched_phrase=_extract_phrase(matched),
            confidence=None,  # Phase 2 confidence not applicable for keyword match
            message_summary=summary,
        )

    logger.debug(
        "urgency_keyword_no_match",
        extra={"elapsed_ms": round(elapsed_ms, 2), "pattern_count": len(patterns)},
    )

    return UrgencyDetectionResult(
        is_urgent=False,
        detection_phase=DetectionPhase.NONE,
        matched_phrase=None,
        confidence=None,
        message_summary=None,
    )


def _extract_phrase(compiled_pattern: str) -> str:
    """Extract the human-readable phrase from a compiled regex pattern string.

    Strips word-boundary anchors and re.escape artefacts to return the
    original keyword phrase as it appeared in urgency_keywords.yaml.

    Example:
        r'\\bchest\\ pain\\b'  →  'chest pain'
    """
    phrase = compiled_pattern
    # Remove word boundary anchors added in config_loader.py
    phrase = phrase.lstrip(r"\b").rstrip(r"\b")
    # Unescape re.escape artefacts (e.g. '\ ' → ' ')
    phrase = re.sub(r"\\(.)", r"\1", phrase)
    return phrase.strip()
```

---

## Validation Checklist

```bash
# Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('backend/app/agents/patient_comm/urgency/keyword_matcher.py').read_text())
print('keyword_matcher.py — syntax OK')
"

# Functional smoke tests (no pytest required at this stage)
python -c "
from backend.app.agents.patient_comm.urgency.keyword_matcher import detect_urgency_keyword
from backend.app.agents.patient_comm.urgency.schemas import DetectionPhase

# AC Scenario 2 — all required keywords trigger Phase 1
required_msgs = [
    ('I have chest pain and can\\'t breathe', 'chest pain'),
    ('there is severe bleeding', 'severe bleeding'),
    ('she is unconscious', 'unconscious'),
    ('he had a stroke', 'stroke'),
    ('I want to commit suicide', 'suicide'),
]
for msg, expected_phrase in required_msgs:
    result = detect_urgency_keyword(msg)
    assert result.is_urgent, f'Expected urgent for: {msg!r}'
    assert result.detection_phase == DetectionPhase.KEYWORD
    assert expected_phrase in result.matched_phrase.lower(), f'Expected phrase {expected_phrase!r} in {result.matched_phrase!r}'
    print(f'✓ Keyword match: {expected_phrase!r}')

# AC Scenario 4 — non-urgent message does not trigger
result = detect_urgency_keyword('when should I take my metformin?')
assert not result.is_urgent
assert result.detection_phase == DetectionPhase.NONE
print('✓ Non-urgent message not flagged')

# Latency: 10 consecutive scans should all complete in <100ms total
import time
msgs = ['when should I take my metformin?'] * 10
t0 = time.perf_counter()
for m in msgs:
    detect_urgency_keyword(m)
elapsed = (time.perf_counter() - t0) * 1_000
assert elapsed < 100, f'10 scans took {elapsed:.1f}ms — exceeds 100ms budget'
print(f'✓ 10 × non-urgent scans completed in {elapsed:.1f}ms (<100ms)')
print('All Phase 1 smoke tests passed ✓')
"
```

---

## Definition of Done

- [ ] `backend/app/agents/patient_comm/urgency/keyword_matcher.py` created
- [ ] `detect_urgency_keyword()` returns `is_urgent=True` with `detection_phase=KEYWORD` for all AC Scenario 2 phrases
- [ ] `detect_urgency_keyword()` returns `is_urgent=False` with `detection_phase=NONE` for non-urgent messages
- [ ] `message_summary` contains only the matched keyword phrase — never the raw patient message
- [ ] No PHI logged: logger calls contain only `matched_phrase` and `elapsed_ms`, never `patient_message`
- [ ] `_extract_phrase()` correctly strips regex artefacts to return human-readable keyword
- [ ] Syntax check passes
- [ ] All functional smoke tests pass
