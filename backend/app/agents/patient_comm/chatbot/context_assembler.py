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

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.app.agents.patient_comm.chatbot.schemas import (
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
