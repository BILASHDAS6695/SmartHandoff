---
id: TASK-004
title: "Implement `DocumentationAgent` — Gemini 1.5 Pro Structured Output with Async Streaming"
user_story: US-025
epic: EP-004
sprint: 2
layer: Backend — AI Agent
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-024, TASK-001, TASK-002, TASK-003]
---

# TASK-004: Implement `DocumentationAgent` — Gemini 1.5 Pro Structured Output with Async Streaming

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI Agent | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements the core `DocumentationAgent` class. It:
1. Extends `BaseAgent` (US-024) and subscribes to the `docs-agent-sub` Pub/Sub subscription
2. Processes A03 (discharge) and A02 (transfer) ADT event types
3. Orchestrates: FHIR fetch → prompt render → Gemini 1.5 Pro call → structured output → DB write
4. Uses LangChain's `with_structured_output(DischargeSummarySchema)` for type-safe JSON extraction
5. Streams tokens via `generate_content_async` to reduce perceived latency

The timeout and template fallback logic lives in TASK-005. This task wires the happy path (AI generation) only. TASK-005 wraps this agent's LLM call with the timeout decorator.

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 1** | `Document` record created with `status=PENDING_REVIEW` within 30s for 95% of cases |
| **Scenario 3** | Structured output includes all six mandatory sections via `DischargeSummarySchema` enforcement |

---

## Implementation Steps

### 1. Create `agents/documentation/agent.py`

```python
"""
DocumentationAgent — AI discharge summary generation.

Subscribes to GCP Pub/Sub `docs-agent-sub` subscription.
Processes A03 (discharge) and A02 (transfer) ADT events.
Generates structured discharge summaries via Vertex AI Gemini 1.5 Pro.
Timeout and template fallback logic is applied by the calling layer (TASK-005).
"""
from __future__ import annotations

import logging
import time
from typing import Literal

from langchain_google_vertexai import ChatVertexAI
from langchain_core.prompts import PromptTemplate

from agents.base_agent import BaseAgent  # US-024
from agents.documentation.fhir_fetcher import FHIREncounterFetcher
from agents.documentation.prompt_renderer import PromptRenderer
from agents.documentation.schemas import DischargeSummarySchema, GenerationType
from db.repositories.document_repository import DocumentRepository
from integrations.fhir_client import FHIRClient

logger = logging.getLogger(__name__)

# ADT event types this agent handles
_SUPPORTED_EVENT_TYPES: frozenset[str] = frozenset({"A03", "A02"})


class DocumentationAgent(BaseAgent):
    """
    AI Documentation Agent.

    Orchestrates: FHIR fetch → prompt render → Gemini structured output → Document DB write.

    Inherits:
        BaseAgent: Pub/Sub consumer, retry logic, DLQ forwarding, health endpoint (US-024).

    Args:
        fhir_client: Async FHIR R4 HTTP client (US-017).
        document_repository: Document ORM repository (US-006).
        project_id: GCP project ID for Vertex AI.
        location: GCP region for Vertex AI endpoint (e.g. 'us-central1').
    """

    SUBSCRIPTION_ID = "docs-agent-sub"

    def __init__(
        self,
        fhir_client: FHIRClient,
        document_repository: DocumentRepository,
        project_id: str,
        location: str = "us-central1",
    ) -> None:
        super().__init__(subscription_id=self.SUBSCRIPTION_ID)

        self._fetcher = FHIREncounterFetcher(fhir_client)
        self._renderer = PromptRenderer()
        self._doc_repo = document_repository

        # LangChain Vertex AI Gemini 1.5 Pro
        # response_mime_type="application/json" enables structured JSON output mode
        self._llm = ChatVertexAI(
            model_name="gemini-1.5-pro",
            project=project_id,
            location=location,
            temperature=0.1,        # Low temperature for deterministic clinical content
            max_output_tokens=4096,
            streaming=True,         # Incremental token delivery reduces perceived latency (TR-004)
            model_kwargs={
                "generation_config": {
                    "response_mime_type": "application/json",
                }
            },
        )

        # LangChain chain: structured output enforces DischargeSummarySchema
        self._chain = self._llm.with_structured_output(DischargeSummarySchema)

    # -------------------------------------------------------------------------
    # BaseAgent interface
    # -------------------------------------------------------------------------

    def can_handle(self, event_type: str) -> bool:
        """Returns True for A03 (discharge) and A02 (transfer) ADT events."""
        return event_type in _SUPPORTED_EVENT_TYPES

    async def process(self, event: dict) -> None:
        """
        Main processing entry point called by BaseAgent on each Pub/Sub message.

        Args:
            event: Deserialised ADT event dict with keys:
                   `event_type` (str), `encounter_id` (str), `occurred_at` (str).

        Raises:
            Does NOT raise — all errors are caught, logged, and the message is
            nacked to trigger Pub/Sub retry / DLQ forwarding via BaseAgent.
        """
        encounter_id: str = event["encounter_id"]
        event_type: str = event["event_type"]

        logger.info(
            "DocumentationAgent processing event",
            extra={"encounter_id": encounter_id, "event_type": event_type},
        )

        start_ms = time.monotonic_ns() // 1_000_000

        # Step 1: Fetch PHI-minimised FHIR encounter context
        encounter_context = await self._fetcher.fetch(encounter_id)

        # Step 2: Render Jinja2 prompt
        prompt_text = self._renderer.render_discharge_summary(encounter_context)

        # Step 3: Invoke Gemini 1.5 Pro with structured output
        # Note: timeout wrapping is applied by the caller (TASK-005)
        summary: DischargeSummarySchema = await self._chain.ainvoke(prompt_text)
        summary.generation_duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        summary.generation_type = GenerationType.AI

        # Step 4: Persist Document record (TASK-006)
        await self._doc_repo.create_discharge_document(
            encounter_id=encounter_id,
            summary=summary,
        )

        logger.info(
            "Discharge summary generated and persisted",
            extra={
                "encounter_id": encounter_id,
                "generation_type": summary.generation_type.value,
                "duration_ms": summary.generation_duration_ms,
            },
        )
```

### 2. Register Agent in `agents/registry.py`

Add `DocumentationAgent` to the agent registry alongside the other agents:

```python
from agents.documentation.agent import DocumentationAgent

AGENT_REGISTRY = [
    # ... existing agents ...
    DocumentationAgent,
]
```

### 3. Wire Agent in `main.py` (Cloud Run entry point)

```python
from agents.documentation.agent import DocumentationAgent

# Dependency injection
documentation_agent = DocumentationAgent(
    fhir_client=fhir_client,
    document_repository=document_repository,
    project_id=settings.GCP_PROJECT_ID,
    location=settings.GCP_REGION,
)
agent_runner.register(documentation_agent)
```

### 4. Unit Tests — `tests/agents/documentation/test_agent.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.documentation.agent import DocumentationAgent
from agents.documentation.schemas import DischargeSummarySchema, GenerationType


MOCK_EVENT_A03 = {
    "event_type": "A03",
    "encounter_id": "ENC-001",
    "occurred_at": "2026-07-14T10:00:00Z",
}

MOCK_SUMMARY = DischargeSummarySchema(
    encounter_id="ENC-001",
    diagnosis_summary=[{"icd10_code": "E11.9", "description": "Type 2 diabetes", "is_primary": True}],
    procedures=[],
    medications_at_discharge=[{"drug_name": "metformin", "dose": "500 mg", "frequency": "twice daily", "route": "oral"}],
    follow_up_instructions=[{"instruction": "Follow up with PCP within 7 days"}],
    warning_signs=["Shortness of breath"],
    activity_restrictions=["No heavy lifting"],
)


@pytest.fixture
def agent(mock_fhir_client, mock_doc_repo):
    with patch("agents.documentation.agent.ChatVertexAI"):
        doc_agent = DocumentationAgent(
            fhir_client=mock_fhir_client,
            document_repository=mock_doc_repo,
            project_id="test-project",
        )
        doc_agent._chain = AsyncMock(return_value=MOCK_SUMMARY)
        doc_agent._fetcher.fetch = AsyncMock(return_value=MagicMock(encounter_id="ENC-001"))
        doc_agent._renderer.render_discharge_summary = MagicMock(return_value="rendered prompt")
        return doc_agent


def test_can_handle_a03(agent):
    assert agent.can_handle("A03") is True


def test_can_handle_a02(agent):
    assert agent.can_handle("A02") is True


def test_cannot_handle_a01(agent):
    assert agent.can_handle("A01") is False


@pytest.mark.asyncio
async def test_process_creates_document(agent, mock_doc_repo):
    await agent.process(MOCK_EVENT_A03)
    mock_doc_repo.create_discharge_document.assert_awaited_once()
    call_kwargs = mock_doc_repo.create_discharge_document.call_args.kwargs
    assert call_kwargs["encounter_id"] == "ENC-001"
    assert call_kwargs["summary"].generation_type == GenerationType.AI
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/agents/documentation/agent.py` |
| **Update** | `backend/agents/registry.py` |
| **Update** | `backend/main.py` |
| **Create** | `backend/tests/agents/documentation/test_agent.py` |

---

## Definition of Done

- [ ] `DocumentationAgent` extends `BaseAgent`; `SUBSCRIPTION_ID = "docs-agent-sub"`
- [ ] `can_handle()` returns `True` for `"A03"` and `"A02"` only
- [ ] `process()` orchestrates: FHIR fetch → prompt render → `_chain.ainvoke()` → `create_discharge_document()`
- [ ] `ChatVertexAI` configured with `streaming=True` and `response_mime_type="application/json"`
- [ ] `with_structured_output(DischargeSummarySchema)` chain enforces Pydantic validation on LLM output
- [ ] `generation_type=AI` and `generation_duration_ms` set on the summary before DB write
- [ ] All 4 unit tests pass

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-024 | Story | `BaseAgent` with Pub/Sub consumer, retry, and DLQ must be implemented |
| TASK-001 | Task | `DischargeSummarySchema` used as `with_structured_output` target |
| TASK-002 | Task | `FHIREncounterFetcher` injected as `self._fetcher` |
| TASK-003 | Task | `PromptRenderer` injected as `self._renderer` |
| TASK-006 | Task | `DocumentRepository.create_discharge_document()` must be implemented |
| langchain-google-vertexai | Library | Add to `pyproject.toml` if not already present |
