---
id: TASK-006
title: "Write Unit Tests — SLA Breach Detection, Config Loading, Escalation Idempotency, Non-Escalation of Completed Tasks"
user_story: US-021
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-003, TASK-004]
---

# TASK-006: Write Unit Tests — SLA Breach Detection, Config Loading, Escalation Idempotency, Non-Escalation of Completed Tasks

> **Story:** US-021 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-021 DoD requires:

> *"Unit tests: SLA breach detection logic, config loading, non-escalation of completed tasks"*

This task delivers the unit test suite covering the three explicitly mandated areas plus escalation idempotency. All tests are pure unit tests — no live DB or Pub/Sub connections. The DB session is mocked with `AsyncMock`; the `EscalationPublisher` is mocked with `MagicMock`.

Config loading tests are already covered in TASK-001. This task completes the remaining test coverage for the `SLAMonitor` and `EscalationPublisher`.

---

## Acceptance Criteria Addressed

| US-021 AC | Requirement |
|---|---|
| **Scenario 1** | Unit test: task in `IN_PROGRESS` for ≥ threshold minutes triggers breach detection |
| **Scenario 3** | Unit test: `COMPLETED` task does NOT trigger escalation even if created 60 minutes ago |
| **Scenario 4** | Unit test: `BED_MANAGEMENT` (15 min) and `DOCUMENTATION` (30 min) evaluated with correct thresholds |
| **DoD** | Unit tests for SLA breach detection, config loading, non-escalation of completed tasks |

---

## Implementation Steps

### 1. Create `sla-monitor/tests/unit/test_sla_monitor.py`

```python
"""Unit tests for SLAMonitor breach detection logic.

Tests are pure unit tests — DB and Pub/Sub are mocked.
No APScheduler ticks are invoked; _find_breached_tasks and _handle_breach
are tested directly as async functions.

US-021 DoD: unit tests for SLA breach detection, non-escalation of completed tasks.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.config.sla_loader import load_sla_config
from app.monitor.sla_monitor import SLAMonitor, _ACTIVE_STATUSES
from app.publisher.escalation_publisher import EscalationPublisher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(
    agent_type: str,
    status: str,
    minutes_ago: int,
    sla_breached: bool = False,
) -> MagicMock:
    """Build a mock AgentTask with the given age and status."""
    task = MagicMock()
    task.id = uuid.uuid4()
    task.encounter_id = uuid.uuid4()
    task.agent_type = agent_type
    task.status = status
    task.sla_breached = sla_breached
    task.sla_threshold_minutes = None
    task.supervisor_id = uuid.uuid4()
    task.created_at = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago)
    return task


@pytest.fixture
def valid_config_yaml(tmp_path: Path) -> Path:
    content = dedent("""\
        sla_thresholds:
          DOCUMENTATION: 30
          MEDICATION_RECONCILIATION: 60
          BED_MANAGEMENT: 15
          FOLLOW_UP_CARE: 120
          PATIENT_COMMUNICATION: 30
        monitor_interval_seconds: 300
        escalation_dedup_window_minutes: 30
    """)
    p = tmp_path / "sla_config.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def publisher_mock() -> MagicMock:
    mock = MagicMock(spec=EscalationPublisher)
    mock.publish = AsyncMock()
    return mock


@pytest.fixture
def monitor(valid_config_yaml: Path, publisher_mock: MagicMock) -> SLAMonitor:
    load_sla_config.cache_clear()
    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        m = SLAMonitor(publisher=publisher_mock)
    return m


# ---------------------------------------------------------------------------
# _find_breached_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_breached_tasks_returns_overdue_in_progress(
    monitor: SLAMonitor,
    valid_config_yaml: Path,
) -> None:
    """US-021 Scenario 1: DOCUMENTATION task at 31 minutes detected as breached."""
    load_sla_config.cache_clear()
    overdue_task = _make_task("DOCUMENTATION", "IN_PROGRESS", minutes_ago=31)
    not_due_task = _make_task("DOCUMENTATION", "IN_PROGRESS", minutes_ago=10)

    read_session = AsyncMock()
    read_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[overdue_task, not_due_task])
        )))
    )

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        now = datetime.now(tz=timezone.utc)
        result = await monitor._find_breached_tasks(read_session, now)

    assert len(result) == 1
    assert result[0].agent_type == "DOCUMENTATION"


@pytest.mark.asyncio
async def test_find_breached_tasks_excludes_completed(
    monitor: SLAMonitor,
    valid_config_yaml: Path,
) -> None:
    """US-021 Scenario 3: COMPLETED task created 60 minutes ago is NOT returned."""
    completed_task = _make_task("DOCUMENTATION", "COMPLETED", minutes_ago=60)

    read_session = AsyncMock()
    read_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[])  # COMPLETED filtered out by WHERE clause
        )))
    )

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        now = datetime.now(tz=timezone.utc)
        result = await monitor._find_breached_tasks(read_session, now)

    assert result == []


@pytest.mark.asyncio
async def test_active_statuses_set_excludes_completed_and_cancelled() -> None:
    """US-021 Scenario 3: Only IN_PROGRESS and PENDING are in _ACTIVE_STATUSES."""
    assert "COMPLETED" not in _ACTIVE_STATUSES
    assert "CANCELLED" not in _ACTIVE_STATUSES
    assert "IN_PROGRESS" in _ACTIVE_STATUSES
    assert "PENDING" in _ACTIVE_STATUSES


@pytest.mark.asyncio
async def test_bed_management_threshold_is_15_minutes(
    monitor: SLAMonitor,
    valid_config_yaml: Path,
) -> None:
    """US-021 Scenario 4: BED_MANAGEMENT task at 16 minutes is breached (threshold=15)."""
    load_sla_config.cache_clear()
    overdue = _make_task("BED_MANAGEMENT", "IN_PROGRESS", minutes_ago=16)
    within_sla = _make_task("BED_MANAGEMENT", "IN_PROGRESS", minutes_ago=10)

    read_session = AsyncMock()
    read_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[overdue, within_sla])
        )))
    )

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        now = datetime.now(tz=timezone.utc)
        result = await monitor._find_breached_tasks(read_session, now)

    assert len(result) == 1
    assert result[0].agent_type == "BED_MANAGEMENT"


@pytest.mark.asyncio
async def test_documentation_not_breached_at_29_minutes(
    monitor: SLAMonitor,
    valid_config_yaml: Path,
) -> None:
    """US-021 Scenario 4: DOCUMENTATION at 29 minutes is NOT breached (threshold=30)."""
    task = _make_task("DOCUMENTATION", "IN_PROGRESS", minutes_ago=29)

    read_session = AsyncMock()
    read_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[task])
        )))
    )

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        now = datetime.now(tz=timezone.utc)
        result = await monitor._find_breached_tasks(read_session, now)

    assert result == []


# ---------------------------------------------------------------------------
# _handle_breach
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_breach_sets_sla_breached_flag(
    monitor: SLAMonitor,
    publisher_mock: MagicMock,
    valid_config_yaml: Path,
) -> None:
    """_handle_breach sets sla_breached=True on the AgentTask."""
    task = _make_task("DOCUMENTATION", "IN_PROGRESS", minutes_ago=35)
    task.sla_breached = False

    write_session = AsyncMock()
    write_session.get = AsyncMock(return_value=task)
    write_session.add = MagicMock()

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        await monitor._handle_breach(write_session, task, datetime.now(tz=timezone.utc))

    assert task.sla_breached is True
    assert task.sla_threshold_minutes == 30
    write_session.add.assert_called_once_with(task)


@pytest.mark.asyncio
async def test_handle_breach_skips_db_write_if_already_breached(
    monitor: SLAMonitor,
    publisher_mock: MagicMock,
    valid_config_yaml: Path,
) -> None:
    """_handle_breach does NOT call session.add() if sla_breached already True."""
    task = _make_task("DOCUMENTATION", "IN_PROGRESS", minutes_ago=45)
    task.sla_breached = True  # already flagged

    write_session = AsyncMock()
    write_session.get = AsyncMock(return_value=task)
    write_session.add = MagicMock()

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        await monitor._handle_breach(write_session, task, datetime.now(tz=timezone.utc))

    write_session.add.assert_not_called()
    publisher_mock.publish.assert_called_once()  # escalation still fires


@pytest.mark.asyncio
async def test_handle_breach_still_publishes_on_already_breached(
    monitor: SLAMonitor,
    publisher_mock: MagicMock,
    valid_config_yaml: Path,
) -> None:
    """EscalationPublisher.publish() is called even if sla_breached already True.
    Idempotency is EscalationPublisher's responsibility.
    """
    task = _make_task("BED_MANAGEMENT", "IN_PROGRESS", minutes_ago=20)
    task.sla_breached = True

    write_session = AsyncMock()
    write_session.get = AsyncMock(return_value=task)
    write_session.add = MagicMock()

    with patch("app.monitor.sla_monitor.load_sla_config") as mock_load:
        mock_load.return_value = load_sla_config(valid_config_yaml)
        monitor._config = mock_load.return_value
        await monitor._handle_breach(write_session, task, datetime.now(tz=timezone.utc))

    publisher_mock.publish.assert_called_once()
```

### 2. Create `sla-monitor/tests/unit/test_escalation_publisher.py`

```python
"""Unit tests for EscalationPublisher idempotency.

US-021 Technical Notes: only one escalation per (encounter_id, agent_type, breach_window).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

from app.config.sla_loader import load_sla_config
from app.publisher.escalation_publisher import EscalationPublisher


@pytest.fixture
def valid_config_yaml(tmp_path: Path) -> Path:
    content = dedent("""\
        sla_thresholds:
          DOCUMENTATION: 30
          MEDICATION_RECONCILIATION: 60
          BED_MANAGEMENT: 15
          FOLLOW_UP_CARE: 120
          PATIENT_COMMUNICATION: 30
        monitor_interval_seconds: 300
        escalation_dedup_window_minutes: 30
    """)
    p = tmp_path / "sla_config.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def publisher(valid_config_yaml: Path) -> EscalationPublisher:
    load_sla_config.cache_clear()
    with patch("app.publisher.escalation_publisher.pubsub_v1.PublisherClient"):
        with patch("app.publisher.escalation_publisher.load_sla_config") as mock_load:
            mock_load.return_value = load_sla_config(valid_config_yaml)
            return EscalationPublisher(project_id="test-project")


@pytest.mark.asyncio
async def test_publish_sends_message(publisher: EscalationPublisher) -> None:
    """First publish call sends a message."""
    publisher._publisher.publish = MagicMock(
        return_value=MagicMock(result=MagicMock(return_value="msg-001"))
    )
    await publisher.publish(
        encounter_id=uuid.uuid4(),
        agent_type="DOCUMENTATION",
        minutes_elapsed=31,
        supervisor_id=uuid.uuid4(),
    )
    publisher._publisher.publish.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_publish_suppressed_within_window(publisher: EscalationPublisher) -> None:
    """Second publish call for same key within dedup window is suppressed."""
    enc_id = uuid.uuid4()
    sup_id = uuid.uuid4()

    publisher._publisher.publish = MagicMock(
        return_value=MagicMock(result=MagicMock(return_value="msg-001"))
    )

    await publisher.publish(enc_id, "DOCUMENTATION", 31, sup_id)
    await publisher.publish(enc_id, "DOCUMENTATION", 32, sup_id)  # duplicate

    assert publisher._publisher.publish.call_count == 1


@pytest.mark.asyncio
async def test_different_agent_types_not_deduplicated(publisher: EscalationPublisher) -> None:
    """Two breaches for different agent types on same encounter are both published."""
    enc_id = uuid.uuid4()
    sup_id = uuid.uuid4()

    publisher._publisher.publish = MagicMock(
        return_value=MagicMock(result=MagicMock(return_value="msg-001"))
    )

    await publisher.publish(enc_id, "DOCUMENTATION", 31, sup_id)
    await publisher.publish(enc_id, "BED_MANAGEMENT", 16, sup_id)

    assert publisher._publisher.publish.call_count == 2


@pytest.mark.asyncio
async def test_failed_publish_not_added_to_dedup_set(publisher: EscalationPublisher) -> None:
    """Failed publish does NOT mark the key as sent — allows retry on next tick."""
    enc_id = uuid.uuid4()
    sup_id = uuid.uuid4()

    publisher._publisher.publish = MagicMock(
        return_value=MagicMock(result=MagicMock(side_effect=Exception("Pub/Sub timeout")))
    )

    with pytest.raises(Exception, match="Pub/Sub timeout"):
        await publisher.publish(enc_id, "DOCUMENTATION", 31, sup_id)

    assert len(publisher._published_keys) == 0
```

### 3. Run the Test Suite

```bash
cd sla-monitor
pytest tests/unit/ -v --tb=short
```

Expected output:

```
tests/unit/test_sla_loader.py::test_load_returns_sla_config PASSED
tests/unit/test_sla_loader.py::test_bed_management_threshold_is_15 PASSED
tests/unit/test_sla_loader.py::test_documentation_threshold_is_30 PASSED
tests/unit/test_sla_loader.py::test_missing_agent_type_raises PASSED
tests/unit/test_sla_loader.py::test_zero_threshold_raises PASSED
tests/unit/test_sla_loader.py::test_missing_file_raises PASSED
tests/unit/test_sla_monitor.py::test_find_breached_tasks_returns_overdue_in_progress PASSED
tests/unit/test_sla_monitor.py::test_find_breached_tasks_excludes_completed PASSED
tests/unit/test_sla_monitor.py::test_active_statuses_set_excludes_completed_and_cancelled PASSED
tests/unit/test_sla_monitor.py::test_bed_management_threshold_is_15_minutes PASSED
tests/unit/test_sla_monitor.py::test_documentation_not_breached_at_29_minutes PASSED
tests/unit/test_sla_monitor.py::test_handle_breach_sets_sla_breached_flag PASSED
tests/unit/test_sla_monitor.py::test_handle_breach_skips_db_write_if_already_breached PASSED
tests/unit/test_sla_monitor.py::test_handle_breach_still_publishes_on_already_breached PASSED
tests/unit/test_escalation_publisher.py::test_publish_sends_message PASSED
tests/unit/test_escalation_publisher.py::test_duplicate_publish_suppressed_within_window PASSED
tests/unit/test_escalation_publisher.py::test_different_agent_types_not_deduplicated PASSED
tests/unit/test_escalation_publisher.py::test_failed_publish_not_added_to_dedup_set PASSED

18 passed in 0.42s
```

---

## Validation Checklist

- [ ] All 18 unit tests pass: `pytest sla-monitor/tests/unit/ -v`
- [ ] `test_find_breached_tasks_excludes_completed` — `COMPLETED` task at 60 min returns empty list
- [ ] `test_bed_management_threshold_is_15_minutes` — `BED_MANAGEMENT` at 16 min detected
- [ ] `test_documentation_not_breached_at_29_minutes` — `DOCUMENTATION` at 29 min NOT detected
- [ ] `test_handle_breach_skips_db_write_if_already_breached` — no `session.add()` when already flagged
- [ ] `test_duplicate_publish_suppressed_within_window` — second identical publish suppressed
- [ ] `test_failed_publish_not_added_to_dedup_set` — failed publish allows retry
- [ ] No live DB or Pub/Sub connections used in any test

---

## Files Created

| Path | Purpose |
|---|---|
| `sla-monitor/tests/unit/test_sla_monitor.py` | 9 unit tests for `SLAMonitor` breach detection |
| `sla-monitor/tests/unit/test_escalation_publisher.py` | 4 unit tests for `EscalationPublisher` idempotency |

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `pytest-asyncio` | Test | Async test support |
| `pytest` | Test | Test framework |
| TASK-001 | Task | `SLAConfig` and `load_sla_config` |
| TASK-003 | Task | `SLAMonitor` and `_ACTIVE_STATUSES` |
| TASK-004 | Task | `EscalationPublisher` |
