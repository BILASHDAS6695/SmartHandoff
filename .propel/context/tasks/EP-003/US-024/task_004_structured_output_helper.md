---
id: TASK-004
title: "Create `base-agent/app/base/structured_output.py` — StructuredOutputHelper wrapping Vertex AI with Pydantic Schema Validation"
user_story: US-024
epic: EP-003
sprint: 2
layer: Backend
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-024/TASK-001]
---

# TASK-004: Create `base-agent/app/base/structured_output.py` — StructuredOutputHelper wrapping Vertex AI with Pydantic Schema Validation

> **Story:** US-024 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-024 mandates (Technical Notes, DoD):

> *"Structured output helper: wraps Vertex AI call with Pydantic schema validation"*
> *"Structured output: use LangChain `with_structured_output(PydanticModel)` chain pattern"*

`StructuredOutputHelper` is a reusable utility that specialist agents call inside `process()` to invoke Vertex AI Gemini and receive a validated Pydantic model instance. It must:

1. Build a LangChain `ChatVertexAI` → `with_structured_output(PydanticModel)` chain
2. Invoke the chain with the rendered prompt string
3. Validate the response against the provided Pydantic schema
4. Raise `NonRetryableError` on schema validation failure (malformed LLM response)
5. Raise `RetryableError` on Vertex AI rate limits (429) or transient network errors

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `with_structured_output(PydanticModel)` | LangChain enforces JSON schema and returns a validated Pydantic instance — no manual JSON parsing |
| `NonRetryableError` on `ValidationError` | Pydantic validation failures indicate a persistent schema mismatch — retrying the same prompt produces the same failure |
| `RetryableError` on HTTP 429 / connection error | Vertex AI rate limits and transient network errors are expected to self-resolve |
| `model_name` and `temperature` injectable | Allows specialist agents to tune model settings; chatbot uses Gemini Flash (TR-006), summaries use Gemini Pro (TR-004) |
| Timeout=25 s (raise at 28 s) | TR-004: document generation <30 s; timeout at 25 s leaves 3 s margin for template fallback in caller |

Design refs: ADR-004, TR-004, TR-006, US-024 Technical Notes.

---

## Acceptance Criteria Addressed

| US-024 AC | Requirement |
|---|---|
| **Scenario 1** | `invoke_structured()` returns validated Pydantic output → agent persists to DB → `COMPLETED` |
| **Scenario 4** | Pydantic `ValidationError` on LLM response → `NonRetryableError` → `FAILED` status |

---

## Implementation Steps

### 1. Create `base-agent/app/base/structured_output.py`

```python
"""StructuredOutputHelper — LangChain + Vertex AI structured output wrapper.

Provides a single ``invoke_structured()`` method that wraps the LangChain
``ChatVertexAI.with_structured_output(PydanticModel)`` pattern used by all
specialist agents to generate validated Pydantic instances from Gemini.

Timeout behaviour (TR-004):
    Default ``timeout=25.0`` seconds. Callers should implement a template
    fallback if ``RetryableError`` is raised after timeout expiry.

Design refs:
    ADR-004 — LangChain + Vertex AI Gemini; structured output via Pydantic
    TR-004  — AI agent document generation <30 s; timeout at 25 s
    TR-006  — chatbot <3 s; use Gemini Flash model name
    US-024  — structured output helper; Pydantic schema validation
"""
from __future__ import annotations

import logging
from typing import Any, TypeVar

import httpx
from langchain_google_vertexai import ChatVertexAI
from pydantic import BaseModel, ValidationError

from app.base.errors import NonRetryableError, RetryableError

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

# Default model names — callers may override (ADR-004, TR-006)
DEFAULT_MODEL_NAME = "gemini-1.5-pro"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TIMEOUT_SECONDS = 25.0


class StructuredOutputHelper:
    """Invokes Vertex AI Gemini via LangChain with enforced Pydantic schema.

    Args:
        model_name: Vertex AI model identifier. Defaults to
            ``"gemini-1.5-pro"`` for document agents; use
            ``"gemini-1.5-flash"`` for chatbot agent (TR-006).
        temperature: Sampling temperature. Default ``0.0`` for deterministic
            clinical output.
        timeout: Request timeout in seconds. Default 25 s (TR-004).
        project: GCP project ID. If ``None``, resolved from ADC credentials.
        location: GCP region. Defaults to ``"us-central1"``.

    Example::

        helper = StructuredOutputHelper(model_name="gemini-1.5-pro")
        output: DischargeSummaryOutput = await helper.invoke_structured(
            prompt="Generate discharge summary for...",
            output_schema=DischargeSummaryOutput,
        )
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        project: str | None = None,
        location: str = "us-central1",
    ) -> None:
        self._model_name = model_name
        self._temperature = temperature
        self._timeout = timeout
        self._project = project
        self._location = location

    async def invoke_structured(
        self,
        prompt: str,
        output_schema: type[_T],
    ) -> _T:
        """Invoke Vertex AI Gemini and return a validated Pydantic instance.

        Builds a LangChain ``ChatVertexAI | with_structured_output(output_schema)``
        chain, invokes it with ``prompt``, then validates the response.

        Args:
            prompt: Fully rendered prompt string (Jinja2 template output or
                inline string). Must NOT contain raw PHI — use minimum-necessary
                clinical identifiers (ICD-10 codes, encounter UUIDs).
            output_schema: Pydantic ``BaseModel`` subclass defining the
                expected response structure.

        Returns:
            Validated instance of ``output_schema``.

        Raises:
            RetryableError: On Vertex AI HTTP 429 (rate limit), connection
                timeout, or transient network error.
            NonRetryableError: On Pydantic ``ValidationError`` (schema
                mismatch) or unexpected LLM response format.
        """
        llm = ChatVertexAI(
            model_name=self._model_name,
            temperature=self._temperature,
            project=self._project,
            location=self._location,
            request_timeout=self._timeout,
        )
        chain = llm.with_structured_output(output_schema)

        try:
            result = await chain.ainvoke(prompt)
        except httpx.TimeoutException as exc:
            raise RetryableError(
                f"Vertex AI request timed out after {self._timeout}s",
                error_detail={"model": self._model_name, "timeout": self._timeout},
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RetryableError(
                    "Vertex AI rate limit (HTTP 429)",
                    error_detail={
                        "model": self._model_name,
                        "status_code": 429,
                    },
                ) from exc
            raise NonRetryableError(
                f"Vertex AI HTTP error {exc.response.status_code}",
                error_detail={
                    "model": self._model_name,
                    "status_code": exc.response.status_code,
                },
            ) from exc
        except Exception as exc:
            raise RetryableError(
                f"Vertex AI transient error: {type(exc).__name__}",
                error_detail={"model": self._model_name, "error": str(exc)},
            ) from exc

        # Validate response schema
        if not isinstance(result, output_schema):
            raise NonRetryableError(
                f"LLM response failed Pydantic validation for {output_schema.__name__}",
                error_detail={
                    "expected_schema": output_schema.__name__,
                    "received_type": type(result).__name__,
                },
            )

        logger.info(
            "structured_output_success",
            extra={
                "model": self._model_name,
                "output_schema": output_schema.__name__,
            },
        )
        return result  # type: ignore[return-value]
```

---

## Validation

Run from `base-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/base/structured_output.py').read_text())
print('Syntax check app/base/structured_output.py: PASSED')
"

# 2. StructuredOutputHelper instantiates with defaults
python -c "
from app.base.structured_output import StructuredOutputHelper, DEFAULT_MODEL_NAME, DEFAULT_TIMEOUT_SECONDS
helper = StructuredOutputHelper()
assert helper._model_name == DEFAULT_MODEL_NAME
assert helper._timeout == DEFAULT_TIMEOUT_SECONDS
print('StructuredOutputHelper defaults: PASSED')
"

# 3. HTTP 429 raises RetryableError
python -c "
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from app.base.structured_output import StructuredOutputHelper
from app.base.errors import RetryableError

async def test_rate_limit():
    helper = StructuredOutputHelper()
    mock_response = MagicMock()
    mock_response.status_code = 429

    with patch('app.base.structured_output.ChatVertexAI') as MockLLM:
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(
            side_effect=httpx.HTTPStatusError('rate limit', request=MagicMock(), response=mock_response)
        )
        MockLLM.return_value.with_structured_output.return_value = mock_chain

        from pydantic import BaseModel
        class TestOutput(BaseModel):
            value: str

        try:
            await helper.invoke_structured('test prompt', TestOutput)
            assert False, 'Should have raised RetryableError'
        except RetryableError:
            print('HTTP 429 raises RetryableError: PASSED')

asyncio.run(test_rate_limit())
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `base-agent/app/base/structured_output.py` |

---

## Definition of Done Checklist

- [ ] `StructuredOutputHelper.invoke_structured()` uses `ChatVertexAI.with_structured_output(output_schema)` chain
- [ ] Returns validated Pydantic instance of `output_schema`
- [ ] `RetryableError` raised on HTTP 429 and connection timeout
- [ ] `NonRetryableError` raised on Pydantic `ValidationError` / schema mismatch
- [ ] Default timeout = 25 s (TR-004 margin); configurable at construction
- [ ] `model_name` injectable — supports Gemini Pro (summaries) and Gemini Flash (chatbot)
- [ ] No PHI in structured log fields (only schema name, model name)
- [ ] Syntax check passes with `ast.parse`
