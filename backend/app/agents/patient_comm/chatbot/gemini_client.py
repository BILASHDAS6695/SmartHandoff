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

from backend.app.agents.patient_comm.chatbot.schemas import GenerationType

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
