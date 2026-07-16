---
id: TASK-005
title: "Extract `shared-libs/agent_base/` — LangChain Base Agent Shared Library (Pub/Sub Consumer, Structured Output, Retry Wrapper)"
user_story: US-020
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-020/TASK-001, US-020/TASK-002]
---

# TASK-005: Extract `shared-libs/agent_base/` — LangChain Base Agent Shared Library (Pub/Sub Consumer, Structured Output, Retry Wrapper)

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-020 DoD mandates:

> *"LangChain base agent class extracted as a shared library: Pub/Sub consumer, structured output, retry wrapper"*

Five downstream agents (Documentation, Medication Reconciliation, Bed Management, Follow-Up Care, Patient Communication) each share the same Pub/Sub consumer loop, structured output enforcement, and LLM retry wrapper patterns. Duplicating this logic across 5 services violates DRY and creates maintenance risk.

`shared-libs/agent_base/` provides:

1. `BaseAgentSubscriber` — reusable Pub/Sub pull consumer that any agent can subclass (extends `ADTSubscriber` pattern)
2. `StructuredOutputMixin` — enforces Pydantic schema validation on Vertex AI Gemini responses
3. `LLMRetryWrapper` — exponential-backoff retry for transient Vertex AI errors (`ResourceExhausted`, `ServiceUnavailable`)

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Python package in `shared-libs/` installed via `pip install -e` | Each agent Cloud Run image installs `agent_base` from local path; no private PyPI required |
| Abstract base class (ABC) for `BaseAgentSubscriber` | Forces each specialised agent to implement `process_task()` — interface contract |
| `StructuredOutputMixin` with Pydantic v2 | ADR-004: structured output enforced at ORM layer; all agents return typed objects |
| `LLMRetryWrapper` wraps `langchain_google_vertexai.ChatVertexAI` | Centralises retry; each agent configures max_retries and base_delay in constructor |

Design refs: ADR-004, TR-004, FR-020, US-020 DoD.

---

## Acceptance Criteria Addressed

| US-020 AC | Requirement |
|---|---|
| **DoD** | LangChain base agent class extracted; downstream agents use shared `BaseAgentSubscriber` |

---

## Implementation Steps

### 1. Scaffold `shared-libs/agent_base/` package

```
shared-libs/
└── agent_base/
    ├── pyproject.toml
    ├── README.md
    └── agent_base/
        ├── __init__.py
        ├── subscriber.py          ← BaseAgentSubscriber ABC
        ├── structured_output.py   ← StructuredOutputMixin
        └── llm_retry.py           ← LLMRetryWrapper
```

### 2. Create `shared-libs/agent_base/pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=70"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "agent-base"
version = "0.1.0"
description = "SmartHandoff shared LangChain base agent library"
requires-python = ">=3.12"
dependencies = [
    "google-cloud-pubsub>=2.26.1",
    "langchain>=0.2.16",
    "langchain-google-vertexai>=1.0.10",
    "pydantic>=2.9.2",
    "prometheus-client>=0.21.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["agent_base*"]
```

### 3. Create `shared-libs/agent_base/agent_base/subscriber.py`

```python
"""Abstract base class for all SmartHandoff LangChain agent subscribers.

Each specialised agent (Documentation, MedRecon, BedManagement, etc.) subclasses
``BaseAgentSubscriber`` and implements ``process_task()``. The base class owns:

  - Pub/Sub pull subscription lifecycle (``FlowControl(max_messages=10)``)
  - ACK-after-success / NACK-on-exception pattern
  - ``shutdown_event`` for SIGTERM integration (TR-017)
  - Prometheus ``agent_task_processing_latency_seconds`` histogram

Usage::

    class DocumentationAgent(BaseAgentSubscriber):
        async def process_task(self, task: AgentTask) -> None:
            draft = await self._generate_document(task)
            await self._persist_draft(draft)

Design refs:
    ADR-001, ADR-004, TR-015, TR-017, US-020 DoD
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from prometheus_client import Histogram

if TYPE_CHECKING:
    from app.models.agent_task import AgentTask

logger = logging.getLogger(__name__)

AGENT_TASK_LATENCY = Histogram(
    "agent_task_processing_latency_seconds",
    "Time from AgentTask receipt to completion",
    ["agent_type"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0],
)


class BaseAgentSubscriber(ABC):
    """Abstract base for all SmartHandoff agent Pub/Sub consumers.

    Subclasses must implement ``process_task(task: AgentTask) -> None``.

    Args:
        agent_type: Identifies this agent in metrics/logs (e.g. "DOCUMENTATION").
        subscription_id: Pub/Sub subscription ID for this agent.
        project_id: GCP project ID.
    """

    def __init__(
        self,
        agent_type: str,
        subscription_id: str,
        project_id: str,
    ) -> None:
        self.agent_type = agent_type
        self._subscription_id = subscription_id
        self._project_id = project_id
        self.shutdown_event: asyncio.Event = asyncio.Event()

    @abstractmethod
    async def process_task(self, task: "AgentTask") -> None:
        """Process a single ``AgentTask``. Implemented by each specialised agent.

        Args:
            task: ``AgentTask`` ORM object in ``PENDING`` status.

        Raises:
            Any exception — causes the Pub/Sub message to be NACKed.
        """
        ...

    async def run(self) -> None:
        """Start the Pub/Sub consumer. Blocks until ``shutdown_event`` is set."""
        from agent_base._internal_subscriber import _run_pull_loop  # noqa: PLC0415

        await _run_pull_loop(self)
```

### 4. Create `shared-libs/agent_base/agent_base/structured_output.py`

```python
"""Structured output enforcement mixin for LangChain + Vertex AI agents.

Provides ``invoke_structured()`` which calls a LangChain chain and validates
the response against a Pydantic v2 schema. On validation failure, the raw
response is logged and a ``StructuredOutputError`` is raised.

Design refs:
    ADR-004  — structured output enforced via Pydantic schemas
    FR-020   — discharge summaries must match defined document schema
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when LLM response cannot be validated against the target schema."""


class StructuredOutputMixin:
    """Mixin that adds ``invoke_structured()`` to a LangChain agent class."""

    async def invoke_structured(
        self,
        chain: "Runnable",
        schema: type[T],
        inputs: dict,
    ) -> T:
        """Invoke ``chain`` and validate the output against ``schema``.

        Args:
            chain: LangChain runnable (prompt | llm | parser).
            schema: Pydantic v2 model class for output validation.
            inputs: Input dict passed to ``chain.ainvoke()``.

        Returns:
            Validated instance of ``schema``.

        Raises:
            StructuredOutputError: If the LLM response fails Pydantic validation.
        """
        raw = await chain.ainvoke(inputs)
        try:
            return schema.model_validate(raw if isinstance(raw, dict) else raw.dict())
        except (ValidationError, AttributeError) as exc:
            logger.error(
                "structured_output_validation_failed",
                extra={
                    "schema": schema.__name__,
                    "error": str(exc),
                },
            )
            raise StructuredOutputError(
                f"LLM output failed {schema.__name__} validation: {exc}"
            ) from exc
```

### 5. Create `shared-libs/agent_base/agent_base/llm_retry.py`

```python
"""Exponential-backoff retry wrapper for Vertex AI LangChain calls.

Wraps any async callable with retry logic for transient Vertex AI errors:
  - ``google.api_core.exceptions.ResourceExhausted`` (429)
  - ``google.api_core.exceptions.ServiceUnavailable`` (503)
  - ``google.api_core.exceptions.DeadlineExceeded`` (504)

Design refs:
    TR-004   — AI document generation <30 seconds; retry with template fallback
    ADR-004  — LangChain abstracts LLM provider; retry wrapper is provider-agnostic
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from google.api_core.exceptions import DeadlineExceeded, ResourceExhausted, ServiceUnavailable

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_EXCEPTIONS = (ResourceExhausted, ServiceUnavailable, DeadlineExceeded)
_DEFAULT_DELAYS = (1.0, 2.0, 4.0, 8.0)  # 4 attempts; total max ~15 s


class LLMRetryWrapper:
    """Wraps an async LLM callable with configurable exponential-backoff retry.

    Args:
        delays: Tuple of sleep durations (seconds) between attempts.
            Length determines the number of retry attempts.

    Example::

        wrapper = LLMRetryWrapper()
        result = await wrapper.call(chain.ainvoke, inputs={"question": "..."})
    """

    def __init__(self, delays: tuple[float, ...] = _DEFAULT_DELAYS) -> None:
        self._delays = delays

    async def call(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """Call ``fn`` with retry on transient Vertex AI errors.

        Args:
            fn: Async callable to invoke (e.g. ``chain.ainvoke``).
            *args, **kwargs: Forwarded to ``fn``.

        Returns:
            Result of ``fn`` on success.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_exc: Exception | None = None

        for attempt, delay in enumerate(self._delays, start=1):
            try:
                return await fn(*args, **kwargs)
            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                logger.warning(
                    "llm_retry",
                    extra={
                        "attempt": attempt,
                        "error": str(exc),
                        "next_delay_seconds": delay if attempt < len(self._delays) else None,
                    },
                )
                if attempt < len(self._delays):
                    await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]
```

### 6. Create `shared-libs/agent_base/agent_base/__init__.py`

```python
"""SmartHandoff shared agent base library.

Exports:
  BaseAgentSubscriber   — ABC for all Pub/Sub-consuming agent containers
  StructuredOutputMixin — Pydantic-validated LangChain chain invocation
  LLMRetryWrapper       — exponential-backoff retry for Vertex AI errors

Design refs:
    ADR-004, TR-004, TR-015, TR-017, US-020 DoD
"""
from agent_base.llm_retry import LLMRetryWrapper
from agent_base.structured_output import StructuredOutputError, StructuredOutputMixin
from agent_base.subscriber import BaseAgentSubscriber

__all__ = [
    "BaseAgentSubscriber",
    "LLMRetryWrapper",
    "StructuredOutputError",
    "StructuredOutputMixin",
]
```

---

## Validation

Run from `shared-libs/agent_base/`:

```bash
# 1. Install in editable mode
pip install -e .

# 2. Syntax check — all modules
for f in agent_base/subscriber.py agent_base/structured_output.py agent_base/llm_retry.py; do
  python -c "
import ast, pathlib
ast.parse(pathlib.Path('$f').read_text())
print('Syntax OK: $f')
"
done

# 3. Import check
python -c "
from agent_base import BaseAgentSubscriber, LLMRetryWrapper, StructuredOutputMixin, StructuredOutputError
print('Import check: PASSED')
"

# 4. LLMRetryWrapper delay defaults
python -c "
from agent_base.llm_retry import LLMRetryWrapper, _DEFAULT_DELAYS
assert len(_DEFAULT_DELAYS) == 4, f'Expected 4 delays, got {len(_DEFAULT_DELAYS)}'
print(f'LLMRetryWrapper delays {_DEFAULT_DELAYS}: PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `shared-libs/agent_base/pyproject.toml` |
| CREATE | `shared-libs/agent_base/agent_base/__init__.py` |
| CREATE | `shared-libs/agent_base/agent_base/subscriber.py` |
| CREATE | `shared-libs/agent_base/agent_base/structured_output.py` |
| CREATE | `shared-libs/agent_base/agent_base/llm_retry.py` |

---

## Definition of Done Checklist

- [ ] `BaseAgentSubscriber` is abstract; `process_task()` is `@abstractmethod`
- [ ] `BaseAgentSubscriber.shutdown_event` is `asyncio.Event` for SIGTERM integration
- [ ] `StructuredOutputMixin.invoke_structured()` raises `StructuredOutputError` on Pydantic validation failure
- [ ] `LLMRetryWrapper._DEFAULT_DELAYS` covers 4 attempts (1s/2s/4s/8s)
- [ ] `LLMRetryWrapper.call()` only retries `ResourceExhausted`, `ServiceUnavailable`, `DeadlineExceeded`
- [ ] Package installable via `pip install -e shared-libs/agent_base/`
- [ ] `coordinator-agent/requirements.txt` references `agent_base` as local dependency
- [ ] All 5 downstream agents' `requirements.txt` updated to include `-e ../../shared-libs/agent_base`
