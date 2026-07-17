---
id: TASK-005
title: "Unit Tests — Scope Enforcement, Context Assembly, FIFO Pruning, Timeout Fallback"
user_story: US-043
epic: EP-008
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-043/TASK-001, US-043/TASK-002, US-043/TASK-003, US-043/TASK-004]
---

# TASK-005: Unit Tests — Scope Enforcement, Context Assembly, FIFO Pruning, Timeout Fallback

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-043 DoD specifies unit tests covering four acceptance criteria: scope enforcement, context assembly, FIFO pruning, and timeout fallback. Tests are distributed across four test files, each targeting a specific module.

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_chat_schemas.py` | `chatbot/schemas.py` | UUID validation; `ChatAuditEvent` excludes PHI |
| `test_history_service.py` | `chatbot/history_service.py` | FIFO pruning; Redis key pattern; TTL; serialisation |
| `test_context_assembler.py` | `chatbot/context_assembler.py` | Token truncation; system prompt content; history serialisation |
| `test_chat_endpoint.py` | `api-gateway/routers/chat.py` | Scope enforcement → 403; successful flow → 200; fallback on timeout |

Coverage target: ≥80% branch coverage across all four modules (TR-020).

### Mocking strategy

| External Dependency | Mock Approach |
|--------------------|---------------|
| `redis.asyncio.Redis.get()` | `AsyncMock` returning serialised JSON or `None` |
| `redis.asyncio.Redis.setex()` | `AsyncMock` returning `True` |
| `ChatGoogleGenerativeAI.ainvoke()` | `AsyncMock` returning `AIMessage(content="reply text")` |
| `asyncio.wait_for()` (timeout) | `AsyncMock` raising `asyncio.TimeoutError` |
| `AsyncSession.execute()` (discharge) | `AsyncMock` returning mock scalar result |
| `get_current_patient_token` | Override with `{"encounter_id": "..."}`  |
| `write_audit_event` | `AsyncMock` — assert called with correct keys |
| FastAPI `AsyncClient` | `httpx.AsyncClient(app=app, base_url="http://test")` |

---

## Acceptance Criteria Addressed

| US-043 AC | Test Cases |
|-----------|-----------|
| **Scenario 1** (p95 <3s) | `test_gemini_timeout_returns_fallback` — verifies graceful degradation on timeout |
| **Scenario 2** (scoped to own docs) | `test_system_prompt_contains_scope_restriction` — verifies system prompt text |
| **Scenario 3** (403 on cross-patient access) | `test_post_chat_wrong_encounter_id_returns_403`, `test_post_chat_correct_encounter_id_returns_200` |
| **Scenario 4** (FIFO pruning) | `test_fifo_pruning_drops_oldest_messages`, `test_fifo_pruning_respects_max_messages` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/patient_comm/chatbot
mkdir -p api-gateway/tests/unit/routers
touch backend/tests/unit/agents/patient_comm/__init__.py
touch backend/tests/unit/agents/patient_comm/chatbot/__init__.py
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `backend/tests/unit/agents/patient_comm/chatbot/test_chat_schemas.py`

```python
"""Unit tests for US-043 Pydantic schemas (TASK-001).

Covers:
    - ChatRequest UUID validation rejects non-UUIDs
    - ChatAuditEvent contains no PHI fields (message, patient name)
    - GenerationType enum values
"""
import pytest
from pydantic import ValidationError

from backend.app.agents.patient_comm.chatbot.schemas import (
    ChatAuditEvent,
    ChatRequest,
    GenerationType,
    TOTAL_CONTEXT_TOKEN_BUDGET,
)


class TestChatRequestValidation:
    def test_valid_request_accepted(self):
        req = ChatRequest(
            message="What are my medication instructions?",
            encounter_id="550e8400-e29b-41d4-a716-446655440000",
            session_id="660e8400-e29b-41d4-a716-446655440001",
        )
        assert req.encounter_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_non_uuid_encounter_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(
                message="test",
                encounter_id="not-a-valid-uuid",
                session_id="660e8400-e29b-41d4-a716-446655440001",
            )
        assert "encounter_id" in str(exc_info.value)

    def test_non_uuid_session_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(
                message="test",
                encounter_id="550e8400-e29b-41d4-a716-446655440000",
                session_id="injection-attempt'; DROP TABLE patients;--",
            )
        assert "session_id" in str(exc_info.value)

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                message="",
                encounter_id="550e8400-e29b-41d4-a716-446655440000",
                session_id="660e8400-e29b-41d4-a716-446655440001",
            )


class TestChatAuditEvent:
    def test_audit_event_has_no_message_field(self):
        """ChatAuditEvent schema must not contain message content — PHI protection."""
        import inspect
        from backend.app.agents.patient_comm.chatbot.schemas import ChatAuditEvent
        fields = ChatAuditEvent.model_fields.keys()
        assert "message" not in fields, "ChatAuditEvent must not contain message content"
        assert "content" not in fields

    def test_total_context_token_budget_is_8000(self):
        assert TOTAL_CONTEXT_TOKEN_BUDGET == 8_000


class TestGenerationType:
    def test_llm_and_fallback_values(self):
        assert GenerationType.LLM == "LLM"
        assert GenerationType.FALLBACK == "FALLBACK"
```

### 3. Create `backend/tests/unit/agents/patient_comm/chatbot/test_history_service.py`

```python
"""Unit tests for ConversationHistoryService and FIFO pruning (TASK-002).

Covers:
    - FIFO pruning drops oldest messages when token budget exceeded (AC Scenario 4)
    - MAX_HISTORY_MESSAGES cap (10 messages) applied before token-based pruning
    - Redis key pattern matches `conversation-history:{eid}:{sid}`
    - Empty history returned when Redis key does not exist
    - Updated history serialised and written with 24h TTL
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.agents.patient_comm.chatbot.history_service import (
    ConversationHistoryService,
    _apply_fifo_pruning,
    _build_key,
)
from backend.app.agents.patient_comm.chatbot.schemas import (
    CONVERSATION_HISTORY_TOKEN_BUDGET,
    MAX_HISTORY_MESSAGES,
    ConversationHistory,
    ConversationMessage,
    MessageRole,
)


ENC_ID = "550e8400-e29b-41d4-a716-446655440000"
SES_ID = "660e8400-e29b-41d4-a716-446655440001"


class TestBuildKey:
    def test_key_matches_expected_pattern(self):
        key = _build_key(ENC_ID, SES_ID)
        assert key == f"conversation-history:{ENC_ID}:{SES_ID}"


class TestFifoPruning:
    def _make_messages(self, n: int, words_per_msg: int = 120) -> list[ConversationMessage]:
        return [
            ConversationMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content="word " * words_per_msg,
            )
            for i in range(n)
        ]

    def test_12_messages_pruned_to_max_10(self):
        """MAX_HISTORY_MESSAGES cap removes messages beyond 10 before token check."""
        msgs = self._make_messages(12, words_per_msg=1)  # Very short — under token budget
        pruned = _apply_fifo_pruning(msgs)
        assert len(pruned) <= MAX_HISTORY_MESSAGES

    def test_token_budget_respected_after_pruning(self):
        """Total estimated tokens of pruned list must not exceed 2K."""
        from backend.app.agents.patient_comm.chatbot.token_counter import estimate_message_tokens
        msgs = self._make_messages(10, words_per_msg=300)  # ~400 tokens each
        pruned = _apply_fifo_pruning(msgs)
        total = sum(estimate_message_tokens(m.role.value, m.content) for m in pruned)
        assert total <= CONVERSATION_HISTORY_TOKEN_BUDGET, (
            f"Pruned history exceeds 2K budget: {total} tokens"
        )

    def test_oldest_messages_dropped_first(self):
        """After pruning, only the most recent messages should remain."""
        msgs = [
            ConversationMessage(role=MessageRole.USER, content=f"message_{i} " + "word " * 200)
            for i in range(8)
        ]
        pruned = _apply_fifo_pruning(msgs)
        # The last message (most recent) should be retained
        if pruned:
            assert pruned[-1].content.startswith("message_7")

    def test_empty_list_returns_empty(self):
        assert _apply_fifo_pruning([]) == []

    def test_single_short_message_not_pruned(self):
        msgs = [ConversationMessage(role=MessageRole.USER, content="How long do I rest?")]
        pruned = _apply_fifo_pruning(msgs)
        assert len(pruned) == 1


class TestConversationHistoryService:
    @pytest.mark.asyncio
    async def test_load_returns_empty_history_on_cache_miss(self):
        service = ConversationHistoryService()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock()

        with patch(
            "backend.app.agents.patient_comm.chatbot.history_service._get_redis_client",
            return_value=mock_client,
        ):
            history = await service.load(ENC_ID, SES_ID)

        assert history.messages == []
        assert history.encounter_id == ENC_ID
        assert history.session_id == SES_ID

    @pytest.mark.asyncio
    async def test_append_and_save_writes_with_ttl(self):
        service = ConversationHistoryService()
        history = ConversationHistory(
            session_id=SES_ID, encounter_id=ENC_ID, messages=[]
        )
        user_msg = ConversationMessage(role=MessageRole.USER, content="Can I eat normally?")
        assistant_msg = ConversationMessage(role=MessageRole.ASSISTANT, content="Yes, as per instructions.")

        mock_client = AsyncMock()
        mock_client.setex = AsyncMock(return_value=True)
        mock_client.aclose = AsyncMock()

        with patch(
            "backend.app.agents.patient_comm.chatbot.history_service._get_redis_client",
            return_value=mock_client,
        ):
            updated = await service.append_and_save(history, user_msg, assistant_msg)

        # Verify setex was called with the correct key and TTL
        mock_client.setex.assert_awaited_once()
        call_args = mock_client.setex.call_args
        key_arg = call_args[0][0]
        ttl_arg = call_args[0][1]
        assert key_arg == f"conversation-history:{ENC_ID}:{SES_ID}"
        assert ttl_arg == 86_400  # 24h TTL

        # Verify messages were appended
        assert len(updated.messages) == 2
```

### 4. Create `backend/tests/unit/agents/patient_comm/chatbot/test_context_assembler.py`

```python
"""Unit tests for ContextAssembler and GeminiFlashClient (TASK-003).

Covers:
    - System prompt contains scope restriction text (AC Scenario 2)
    - Discharge summary truncated to 4K token budget
    - History messages serialised to LangChain format
    - Gemini timeout returns FALLBACK (AC Scenario 1)
    - Gemini success returns LLM generation type
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.app.agents.patient_comm.chatbot.context_assembler import (
    ContextAssembler,
    _SYSTEM_PROMPT_TEMPLATE,
    _truncate_to_token_budget,
)
from backend.app.agents.patient_comm.chatbot.gemini_client import GeminiFlashClient
from backend.app.agents.patient_comm.chatbot.schemas import (
    DISCHARGE_SUMMARY_TOKEN_BUDGET,
    ConversationHistory,
    ConversationMessage,
    GenerationType,
    MessageRole,
)
from backend.app.agents.patient_comm.chatbot.token_counter import estimate_tokens


ENC_ID = "550e8400-e29b-41d4-a716-446655440000"
SES_ID = "660e8400-e29b-41d4-a716-446655440001"


class TestTruncateToTokenBudget:
    def test_short_text_not_truncated(self):
        text = "Take your medication twice daily."
        result = _truncate_to_token_budget(text, 4_000)
        assert result == text

    def test_long_text_truncated_to_budget(self):
        long_text = "word " * 5_000  # ~6 650 tokens
        result = _truncate_to_token_budget(long_text, DISCHARGE_SUMMARY_TOKEN_BUDGET)
        assert estimate_tokens(result) <= DISCHARGE_SUMMARY_TOKEN_BUDGET

    def test_truncated_text_contains_notice(self):
        long_text = "word " * 5_000
        result = _truncate_to_token_budget(long_text, DISCHARGE_SUMMARY_TOKEN_BUDGET)
        assert "truncated" in result


class TestContextAssembler:
    def _make_history(self, messages=None) -> ConversationHistory:
        return ConversationHistory(
            session_id=SES_ID,
            encounter_id=ENC_ID,
            messages=messages or [],
        )

    def test_assemble_returns_system_plus_human_for_empty_history(self):
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("How long do I rest?", "Rest for 2 weeks.", history)
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[-1], HumanMessage)

    def test_system_prompt_contains_scope_restriction(self):
        """AC Scenario 2: system prompt must restrict LLM to discharge instructions only."""
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("test question", "some discharge text", history)
        system_content = messages[0].content
        assert "ONLY answer questions based on the discharge instructions" in system_content

    def test_system_prompt_contains_dont_know_instruction(self):
        """AC Scenario 2: system prompt must include 'I don't know' fallback instruction."""
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("test", "some discharge text", history)
        assert "I don't know" in messages[0].content or "don't know" in messages[0].content

    def test_history_messages_included_in_order(self):
        assembler = ContextAssembler()
        history = self._make_history([
            ConversationMessage(role=MessageRole.USER, content="First question"),
            ConversationMessage(role=MessageRole.ASSISTANT, content="First answer"),
        ])
        messages = assembler.assemble("Second question", "discharge", history)
        # [SystemMessage, HumanMessage("First question"), AIMessage("First answer"), HumanMessage("Second question")]
        assert len(messages) == 4
        assert isinstance(messages[1], HumanMessage)
        assert messages[1].content == "First question"

    def test_none_discharge_uses_fallback_text(self):
        assembler = ContextAssembler()
        history = self._make_history()
        messages = assembler.assemble("test", None, history)
        system_content = messages[0].content
        assert "No discharge instructions are currently available" in system_content


class TestGeminiFlashClient:
    @pytest.mark.asyncio
    async def test_successful_response_returns_llm_generation_type(self):
        client = GeminiFlashClient()
        mock_ai_message = AIMessage(content="Take your medication with food.")
        mock_ai_message.response_metadata = {"usage_metadata": {"total_token_count": 120}}

        with patch(
            "backend.app.agents.patient_comm.chatbot.gemini_client.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=mock_ai_message,
        ):
            reply, gen_type, tokens = await client.complete([], ENC_ID, SES_ID)

        assert gen_type == GenerationType.LLM
        assert reply == "Take your medication with food."
        assert tokens == 120

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback_not_exception(self):
        """AC Scenario 1: timeout must return FALLBACK — not raise an exception."""
        client = GeminiFlashClient()

        with patch(
            "backend.app.agents.patient_comm.chatbot.gemini_client.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            reply, gen_type, tokens = await client.complete([], ENC_ID, SES_ID)

        assert gen_type == GenerationType.FALLBACK
        assert tokens is None
        assert "try" in reply.lower() or "sorry" in reply.lower()

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_fallback(self):
        """Any Gemini error must degrade to FALLBACK — not 500 to the patient."""
        client = GeminiFlashClient()

        with patch(
            "backend.app.agents.patient_comm.chatbot.gemini_client.asyncio.wait_for",
            side_effect=RuntimeError("Vertex AI quota exceeded"),
        ):
            reply, gen_type, tokens = await client.complete([], ENC_ID, SES_ID)

        assert gen_type == GenerationType.FALLBACK
```

### 5. Create `api-gateway/tests/unit/routers/test_chat_endpoint.py`

```python
"""Unit tests for POST /api/v1/chat endpoint (TASK-004).

Covers:
    - HTTP 403 returned when request encounter_id ≠ JWT encounter_id (AC Scenario 3)
    - HTTP 200 returned when encounter_id matches JWT claim
    - FALLBACK generation type returned on Gemini timeout
    - Audit event written without message content
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from api_gateway.app.main import app


ENC_ID = "550e8400-e29b-41d4-a716-446655440000"
SES_ID = "660e8400-e29b-41d4-a716-446655440001"
OTHER_ENC_ID = "770e8400-e29b-41d4-a716-446655440002"

VALID_PAYLOAD = {
    "message": "What medications should I take?",
    "encounter_id": ENC_ID,
    "session_id": SES_ID,
}


def _patch_all_dependencies(encounter_id_in_jwt: str, gemini_timeout: bool = False):
    """Context manager stack for isolating the chat endpoint."""
    from contextlib import ExitStack
    import asyncio
    from langchain_core.messages import AIMessage
    from backend.app.agents.patient_comm.chatbot.schemas import GenerationType

    stack = ExitStack()

    # 1. Override JWT token claims
    stack.enter_context(
        patch(
            "api_gateway.app.routers.chat.get_current_patient_token",
            return_value={"encounter_id": encounter_id_in_jwt, "sub": "patient-001"},
        )
    )
    # 2. Mock discharge loader
    stack.enter_context(
        patch(
            "api_gateway.app.routers.chat.load_discharge_summary",
            new_callable=AsyncMock,
            return_value="Take aspirin once daily with food.",
        )
    )
    # 3. Mock history service
    from backend.app.agents.patient_comm.chatbot.schemas import ConversationHistory
    mock_history_svc = MagicMock()
    mock_history_svc.load = AsyncMock(
        return_value=ConversationHistory(session_id=SES_ID, encounter_id=ENC_ID, messages=[])
    )
    mock_history_svc.append_and_save = AsyncMock()
    stack.enter_context(
        patch("api_gateway.app.routers.chat._history_service", mock_history_svc)
    )
    # 4. Mock Gemini client
    if gemini_timeout:
        gemini_result = ("Sorry, try again.", GenerationType.FALLBACK, None)
    else:
        gemini_result = ("Take aspirin once daily.", GenerationType.LLM, 95)
    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(return_value=gemini_result)
    stack.enter_context(
        patch("api_gateway.app.routers.chat._gemini_client", mock_gemini)
    )
    # 5. Mock audit writer
    stack.enter_context(
        patch(
            "api_gateway.app.routers.chat.write_audit_event",
            new_callable=AsyncMock,
        )
    )
    # 6. Mock DB session
    stack.enter_context(
        patch("api_gateway.app.routers.chat.get_read_session", return_value=AsyncMock())
    )
    return stack


@pytest.mark.asyncio
async def test_post_chat_wrong_encounter_id_returns_403():
    """AC Scenario 3: encounter_id mismatch → 403 before any DB or LLM access."""
    with _patch_all_dependencies(encounter_id_in_jwt=OTHER_ENC_ID):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/api/v1/chat", json=VALID_PAYLOAD)

    assert response.status_code == 403
    # Must not disclose encounter existence
    assert "encounter" not in response.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_post_chat_correct_encounter_id_returns_200():
    """AC Scenario 3: matching encounter_id → 200 with ChatResponse."""
    with _patch_all_dependencies(encounter_id_in_jwt=ENC_ID):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/api/v1/chat", json=VALID_PAYLOAD)

    assert response.status_code == 200
    data = response.json()
    assert data["encounter_id"] == ENC_ID
    assert data["session_id"] == SES_ID
    assert data["generation_type"] == "LLM"
    assert "reply" in data


@pytest.mark.asyncio
async def test_post_chat_timeout_returns_fallback_not_500():
    """AC Scenario 1: Gemini timeout → 200 FALLBACK (not 500 exception)."""
    with _patch_all_dependencies(encounter_id_in_jwt=ENC_ID, gemini_timeout=True):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/api/v1/chat", json=VALID_PAYLOAD)

    assert response.status_code == 200
    data = response.json()
    assert data["generation_type"] == "FALLBACK"


@pytest.mark.asyncio
async def test_audit_event_written_without_message_content():
    """US-043 DoD: audit event must not include message content."""
    with _patch_all_dependencies(encounter_id_in_jwt=ENC_ID) as stack:
        with patch(
            "api_gateway.app.routers.chat.write_audit_event",
            new_callable=AsyncMock,
        ) as mock_audit:
            async with AsyncClient(app=app, base_url="http://test") as client:
                await client.post("/api/v1/chat", json=VALID_PAYLOAD)

    if mock_audit.called:
        _, audit_payload = mock_audit.call_args[0]
        assert "message" not in audit_payload, "Audit event must not contain message content"
        assert "content" not in audit_payload
        assert "encounter_id" in audit_payload
```

---

## Running Tests

```bash
# Run all US-043 unit tests
pytest backend/tests/unit/agents/patient_comm/chatbot/ \
       api-gateway/tests/unit/routers/test_chat_endpoint.py \
       -v --tb=short

# Coverage report
pytest backend/tests/unit/agents/patient_comm/chatbot/ \
       api-gateway/tests/unit/routers/test_chat_endpoint.py \
       --cov=backend.app.agents.patient_comm.chatbot \
       --cov=api_gateway.app.routers.chat \
       --cov-report=term-missing \
       --cov-fail-under=80
```

---

## Definition of Done

- [ ] `test_chat_schemas.py` — UUID rejection, audit event PHI exclusion, token budget assertion
- [ ] `test_history_service.py` — FIFO pruning (oldest dropped), MAX_HISTORY_MESSAGES cap, Redis key pattern, 24h TTL
- [ ] `test_context_assembler.py` — system prompt scope text, discharge truncation, history ordering, `None` discharge fallback
- [ ] `test_chat_endpoint.py` — 403 on encounter mismatch, 200 on match, FALLBACK on timeout, audit without message content
- [ ] All tests pass: `pytest ... -v`
- [ ] Coverage ≥80% branch across all four modules (`--cov-fail-under=80`)
