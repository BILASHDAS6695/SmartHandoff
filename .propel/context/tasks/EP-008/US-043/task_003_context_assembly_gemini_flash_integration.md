---
id: TASK-003
title: "Context Assembly & Gemini Flash Integration — 8K Token Window, 3s Timeout, Fallback"
user_story: US-043
epic: EP-008
sprint: 2
layer: Backend / AI Agent
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-043/TASK-001, US-043/TASK-002, US-025]
---

# TASK-003: Context Assembly & Gemini Flash Integration — 8K Token Window, 3s Timeout, Fallback

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-043 requires two collaborating components:

1. **`ContextAssembler`** — builds the 8 K-token context window from three partitions:
   - **System prompt** (2 K budget): static prompt text that explicitly instructs the LLM to answer only from the patient's own discharge instructions.
   - **Discharge summary** (4 K budget): the `content` field of the patient's approved discharge document (provisioned by US-025/TASK-001), truncated to 4 K tokens using the same approximation from TASK-002.
   - **Conversation history** (2 K budget): the pruned `messages` list from `ConversationHistoryService` (TASK-002), serialised to a `user/assistant` alternating string.

2. **`GeminiFlashClient`** — wraps the LangChain `ChatGoogleGenerativeAI` with model `gemini-1.5-flash`, enforces a **3-second timeout**, and returns a `ChatResponse`. On timeout it returns a graceful fallback message with `generation_type=FALLBACK` — never raises an exception to the endpoint layer.

**System prompt design (US-043 AC Scenario 2):**

```
You are a patient discharge assistant for SmartHandoff. You ONLY answer questions
based on the discharge instructions provided below. Do not use any external medical
knowledge. If the answer is not found in the discharge instructions, respond with:
"I don't know the answer to that from your discharge instructions. Please call the
hospital if you have concerns." Never diagnose, prescribe, or give advice beyond
what appears in the provided instructions. Be concise, clear, and compassionate.

--- DISCHARGE INSTRUCTIONS ---
{discharge_summary}
--- END DISCHARGE INSTRUCTIONS ---
```

**Design references:**
- design.md §4.1 TR-006 — Chatbot response <3 seconds; Gemini Flash (`gemini-1.5-flash`); context 8 K tokens
- design.md §7.3 AIR-020 — Vertex AI JSON output mode; Pydantic schema validation; timeout=25s for other agents; this story uses 3s per TR-006
- design.md §7.3 AIR-021 — PHI minimum-necessary in prompts; no PHI in logs
- design.md §7.3 AIR-022 — fallback on timeout; `generation_type: TEMPLATE` (this story: `FALLBACK`)
- design.md §7.3 AIR-024 — 8 K token budget allocation
- US-043 AC Scenario 2 — system prompt restricts LLM to discharge instructions only
- US-043 AC Scenario 1 — 95th percentile response latency <3 seconds
- US-043 Technical Notes — Gemini Flash for latency; Pro too slow for 3s SLA

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Gemini Flash with 3-second timeout; p95 latency target enforced at the client level |
| Scenario 2 | System prompt explicitly restricts LLM to patient's own discharge instructions |

---

## Implementation Steps

### 1. Create module files

```bash
touch backend/app/agents/patient_comm/chatbot/context_assembler.py
touch backend/app/agents/patient_comm/chatbot/gemini_client.py
touch backend/app/agents/patient_comm/chatbot/discharge_loader.py
```

### 2. Implement `backend/app/agents/patient_comm/chatbot/discharge_loader.py`

```python
"""Loads the approved discharge summary content for a given encounter (US-043).

The discharge document content column is AES-256-GCM encrypted at the ORM layer
(ADR-007, design.md §6.1 DR-002). SQLAlchemy TypeDecorators transparently decrypt
on read — the plaintext string is returned here.

This module returns ONLY the content field — it does NOT return patient name,
MRN, or any other PHI beyond the clinical narrative the LLM is permitted to use
(AIR-021: minimum-necessary principle for LLM prompts).

Design refs:
    US-025 — approved discharge document as context source (dependency)
    design.md §6.1 DR-002 — document.content encrypted via SQLAlchemy TypeDecorator
    design.md §7.3 AIR-021 — minimum-necessary PHI in LLM prompts
    design.md §8.3 — patient role can only access own encounter documents
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Lazy import avoids circular imports — the ORM model is defined in the core DB layer
_DISCHARGE_DOCUMENT_MODEL = None


def _get_document_model():
    global _DISCHARGE_DOCUMENT_MODEL
    if _DISCHARGE_DOCUMENT_MODEL is None:
        from backend.app.db.models import DischargeDocument  # noqa: PLC0415
        _DISCHARGE_DOCUMENT_MODEL = DischargeDocument
    return _DISCHARGE_DOCUMENT_MODEL


async def load_discharge_summary(encounter_id: str, db: AsyncSession) -> str | None:
    """Return the decrypted `content` of the approved discharge document.

    Args:
        encounter_id: UUID of the encounter to look up.
        db: Async SQLAlchemy session bound to the read replica (TASK-004 supplies this).

    Returns:
        The plaintext discharge summary string, or ``None`` if no approved
        document exists yet (e.g. document not yet generated or not yet approved).
    """
    DischargeDocument = _get_document_model()

    stmt = (
        select(DischargeDocument.content)
        .where(
            DischargeDocument.encounter_id == encounter_id,
            DischargeDocument.status == "APPROVED",
        )
        .order_by(DischargeDocument.updated_at.desc())
        .limit(1)
    )

    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        logger.warning(
            "No approved discharge document found for encounter_id=%s; "
            "chatbot will use fallback instructions.",
            encounter_id,
        )
    return row
```

### 3. Implement `backend/app/agents/patient_comm/chatbot/context_assembler.py`

```python
"""Builds the 8K-token context window for the patient chatbot (US-043).

Token budget allocation (design.md AIR-024 / US-043 AC Scenario 4):
    system_prompt     2,000 tokens  (static — includes discharge_summary placeholder)
    discharge_summary 4,000 tokens  (truncated from approved document content)
    conversation_hist 2,000 tokens  (FIFO-pruned by ConversationHistoryService)
    ─────────────────────────────────────
    TOTAL             8,000 tokens

The assembler does NOT prune the conversation history — that is the
responsibility of ConversationHistoryService (TASK-002). It truncates
the discharge summary to fit within DISCHARGE_SUMMARY_TOKEN_BUDGET.

Design refs:
    design.md §7.3 AIR-021 — minimum-necessary PHI; discharge content is clinical text,
        not an identifier, and its inclusion in the prompt is a necessity for this feature
    design.md §7.3 AIR-024 — token budget allocation
    US-043 AC Scenario 2 — system prompt restricts LLM to discharge instructions only
"""
from __future__ import annotations

import math

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.app.agents.patient_comm.chatbot.schemas import (
    CONVERSATION_HISTORY_TOKEN_BUDGET,
    DISCHARGE_SUMMARY_TOKEN_BUDGET,
    ConversationHistory,
    MessageRole,
)
from backend.app.agents.patient_comm.chatbot.token_counter import estimate_tokens

# ---------------------------------------------------------------------------
# System prompt template
# US-043 AC Scenario 2: explicitly restricts the LLM to the patient's discharge
# instructions and provides a mandatory "I don't know" fallback instruction.
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_TEMPLATE = """\
You are a patient discharge assistant for SmartHandoff. You ONLY answer questions \
based on the discharge instructions provided below. Do not use any external medical \
knowledge. If the answer is not found in the discharge instructions, respond with: \
"I don't know the answer to that from your discharge instructions. Please call the \
hospital if you have concerns." Never diagnose, prescribe, or give advice beyond \
what appears in the provided instructions. Be concise, clear, and compassionate.

--- DISCHARGE INSTRUCTIONS ---
{discharge_summary}
--- END DISCHARGE INSTRUCTIONS ---"""

_FALLBACK_DISCHARGE_TEXT = (
    "No discharge instructions are currently available for your encounter. "
    "Please contact the hospital for assistance."
)


def _truncate_to_token_budget(text: str, budget: int) -> str:
    """Truncate *text* so that its estimated token count does not exceed *budget*.

    Truncates at word boundaries to avoid splitting clinical terms.
    Appends a truncation notice if truncation occurred.
    """
    words = text.split()
    # Binary search for the largest prefix that fits in the budget
    lo, hi = 0, len(words)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = " ".join(words[:mid])
        if estimate_tokens(candidate) <= budget:
            lo = mid
        else:
            hi = mid - 1

    result = " ".join(words[:lo])
    if lo < len(words):
        result += "\n[... discharge instructions truncated to fit context window ...]"
    return result


def _serialise_history_to_langchain(history: ConversationHistory) -> list:
    """Convert ConversationHistory.messages to LangChain message objects.

    LangChain ChatGoogleGenerativeAI requires a list of HumanMessage / AIMessage.
    Role mapping:
        MessageRole.USER      → HumanMessage
        MessageRole.ASSISTANT → AIMessage
    """
    lc_messages = []
    for msg in history.messages:
        if msg.role == MessageRole.USER:
            lc_messages.append(HumanMessage(content=msg.content))
        else:
            lc_messages.append(AIMessage(content=msg.content))
    return lc_messages


class ContextAssembler:
    """Assembles the LangChain message list for a single chatbot turn.

    The assembled context is passed directly to GeminiFlashClient.complete().
    """

    def assemble(
        self,
        user_message: str,
        discharge_summary: str | None,
        conversation_history: ConversationHistory,
    ) -> list:
        """Build the full message list for the Gemini Flash API call.

        Args:
            user_message: The current patient question (raw text, not yet in history).
            discharge_summary: Decrypted discharge document content from discharge_loader.
                If None, uses _FALLBACK_DISCHARGE_TEXT with a warning embedded.
            conversation_history: Pruned history from ConversationHistoryService.

        Returns:
            List of LangChain message objects: [SystemMessage, ...history..., HumanMessage]
        """
        # 1. Truncate discharge summary to 4K token budget
        discharge_text = discharge_summary if discharge_summary else _FALLBACK_DISCHARGE_TEXT
        truncated_discharge = _truncate_to_token_budget(
            discharge_text, DISCHARGE_SUMMARY_TOKEN_BUDGET
        )

        # 2. Build system prompt (includes truncated discharge summary)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            discharge_summary=truncated_discharge
        )

        # 3. Build history messages (already FIFO-pruned to 2K token budget by TASK-002)
        history_messages = _serialise_history_to_langchain(conversation_history)

        # 4. Combine: [system] + [history...] + [current user turn]
        return [
            SystemMessage(content=system_prompt),
            *history_messages,
            HumanMessage(content=user_message),
        ]
```

### 4. Implement `backend/app/agents/patient_comm/chatbot/gemini_client.py`

```python
"""Vertex AI Gemini Flash client for the patient chatbot (US-043).

Uses LangChain ChatGoogleGenerativeAI with model `gemini-1.5-flash`.

Timeout behaviour (US-043 DoD / design.md AIR-022):
    - Hard timeout: 3.0 seconds (asyncio.wait_for).
    - On TimeoutError: returns a graceful FALLBACK ChatResponse — never raises.
    - The Angular client receives generation_type=FALLBACK and can display
      a user-friendly "please try again" message.

PHI safety (design.md AIR-021):
    - The `messages` list passed to Gemini MAY contain discharge content (clinical text).
    - Vertex AI is configured with `candidate_count=1`, `temperature=0.2` — no
      variation that could induce hallucination beyond discharge content.
    - Cloud Logging for the patient-comm service is configured to exclude
      the `content` field from any log entry (enforced by the log sanitiser
      middleware — design.md §3.3).

Design refs:
    design.md §4.1 TR-006 — Gemini Flash; 3s timeout; context 8K tokens
    design.md §7.3 AIR-020 — Pydantic schema validation on LLM output
    design.md §7.3 AIR-022 — timeout → fallback; flagged as FALLBACK
    US-043 AC Scenario 1 — p95 response latency <3 seconds
    US-043 Technical Notes — `gemini-1.5-flash`; Pro too slow for 3s SLA
"""
from __future__ import annotations

import asyncio
import logging
import os

from langchain_google_genai import ChatGoogleGenerativeAI

from backend.app.agents.patient_comm.chatbot.schemas import ChatResponse, GenerationType

logger = logging.getLogger(__name__)

# Timeout enforced by asyncio.wait_for — US-043 DoD / TR-006
_GEMINI_TIMEOUT_SECONDS: float = 3.0

_FALLBACK_REPLY = (
    "I'm sorry, I wasn't able to retrieve an answer in time. "
    "Please try your question again, or call the hospital if your concern is urgent."
)


def _build_llm() -> ChatGoogleGenerativeAI:
    """Instantiate the LangChain Gemini Flash client.

    Model: gemini-1.5-flash — selected for sub-3s latency (US-043 Technical Notes).
    Temperature: 0.2 — low variation; keeps answers close to discharge content.
    GCP project and location are injected via env vars (TR-021 — no hardcoded credentials).
    """
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.2,
        max_output_tokens=512,
        project=os.environ["GCP_PROJECT_ID"],
        location=os.environ.get("VERTEX_AI_LOCATION", "us-central1"),
    )


class GeminiFlashClient:
    """Async client for Gemini Flash chatbot completions.

    Usage:
        client = GeminiFlashClient()
        response = await client.complete(
            messages=assembled_messages,
            encounter_id=encounter_id,
            session_id=session_id,
        )
    """

    async def complete(
        self,
        messages: list,
        encounter_id: str,
        session_id: str,
    ) -> tuple[str, GenerationType, int | None]:
        """Call Gemini Flash and return (reply_text, generation_type, tokens_used).

        On timeout, returns (_FALLBACK_REPLY, FALLBACK, None) without raising.

        Args:
            messages: LangChain message list from ContextAssembler.assemble().
            encounter_id: Used only for structured log context (no PHI).
            session_id: Used only for structured log context.

        Returns:
            Tuple of (reply_text, generation_type, tokens_used_or_None).
        """
        llm = _build_llm()

        try:
            ai_message = await asyncio.wait_for(
                llm.ainvoke(messages),
                timeout=_GEMINI_TIMEOUT_SECONDS,
            )
            reply_text = ai_message.content
            # LangChain response_metadata may include usage_metadata from Gemini
            tokens_used: int | None = None
            if hasattr(ai_message, "response_metadata"):
                usage = ai_message.response_metadata.get("usage_metadata", {})
                total = usage.get("total_token_count")
                if isinstance(total, int):
                    tokens_used = total

            logger.info(
                "Gemini Flash response received; encounter_id=%s session_id=%s "
                "tokens_used=%s generation_type=LLM",
                encounter_id,
                session_id,
                tokens_used,
            )
            return reply_text, GenerationType.LLM, tokens_used

        except asyncio.TimeoutError:
            logger.warning(
                "Gemini Flash timeout after %.1fs; returning fallback; "
                "encounter_id=%s session_id=%s",
                _GEMINI_TIMEOUT_SECONDS,
                encounter_id,
                session_id,
            )
            return _FALLBACK_REPLY, GenerationType.FALLBACK, None

        except Exception:
            logger.exception(
                "Unexpected Gemini Flash error; returning fallback; "
                "encounter_id=%s session_id=%s",
                encounter_id,
                session_id,
            )
            return _FALLBACK_REPLY, GenerationType.FALLBACK, None
```

---

## Validation Checklist

```bash
# Syntax check — all three modules
python -c "
import ast, pathlib
for f in [
    'backend/app/agents/patient_comm/chatbot/discharge_loader.py',
    'backend/app/agents/patient_comm/chatbot/context_assembler.py',
    'backend/app/agents/patient_comm/chatbot/gemini_client.py',
]:
    ast.parse(pathlib.Path(f).read_text())
    print(f'{f} — syntax OK')
"

# Context assembler unit check (no external deps)
python -c "
from backend.app.agents.patient_comm.chatbot.context_assembler import (
    ContextAssembler, _truncate_to_token_budget
)
from backend.app.agents.patient_comm.chatbot.schemas import ConversationHistory

assembler = ContextAssembler()
long_text = 'word ' * 5000  # ~6 650 estimated tokens — exceeds 4 K budget
history = ConversationHistory(session_id='s1', encounter_id='e1', messages=[])
messages = assembler.assemble('What are my restrictions?', long_text, history)

# Should have SystemMessage + HumanMessage
assert len(messages) == 2, f'Expected 2 messages, got {len(messages)}'

# Check discharge text was truncated
from langchain_core.messages import SystemMessage
system_content = messages[0].content
assert 'truncated' in system_content or len(system_content) < len(long_text)
print('ContextAssembler.assemble — truncation and assembly ✓')
"
```

---

## Definition of Done

- [ ] `backend/app/agents/patient_comm/chatbot/discharge_loader.py` created — reads `APPROVED` discharge document; returns `None` if not found
- [ ] `backend/app/agents/patient_comm/chatbot/context_assembler.py` created — truncates discharge to 4 K tokens; assembles [SystemMessage, …history…, HumanMessage]
- [ ] `backend/app/agents/patient_comm/chatbot/gemini_client.py` created — `gemini-1.5-flash`; 3-second `asyncio.wait_for`; `FALLBACK` returned on timeout
- [ ] System prompt includes "You ONLY answer questions based on the discharge instructions" and "I don't know" instruction (AC Scenario 2)
- [ ] `GeminiFlashClient.complete()` never raises to the endpoint layer — all exceptions caught and converted to `FALLBACK`
- [ ] No PHI field names (`mrn`, `first_name`, `last_name`) appear in `logger.*` calls
- [ ] `GCP_PROJECT_ID` and `VERTEX_AI_LOCATION` read from env vars — no hardcoded values (TR-021)
- [ ] Syntax check passes without errors
