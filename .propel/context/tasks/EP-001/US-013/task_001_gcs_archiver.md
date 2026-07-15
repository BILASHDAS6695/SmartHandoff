---
id: TASK-001
title: "Create `hl7-listener/app/archive/gcs_archiver.py` — GCS Archiver (Path Builder, Atomic Upload, Exponential-Backoff Retry)"
user_story: US-013
epic: EP-001
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-011/TASK-001]
---

# TASK-001: Create `hl7-listener/app/archive/gcs_archiver.py` — GCS Archiver (Path Builder, Atomic Upload, Exponential-Backoff Retry)

> **Story:** US-013 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-013 mandates (AIR-003):

> *"Every raw HL7 message written to Cloud Storage (HIPAA bucket) before ACK — guarantees replay capability; path: `hl7-archive/{year}/{month}/{day}/{message-id}.hl7`"*

`GCSArchiver` is the single module responsible for writing raw HL7 bytes to Cloud Storage. It must be invoked **before** the ACK TCP response is dispatched (SC-1), handle transient GCS errors with 3-attempt exponential backoff (SC-4), and delegate to the fallback queue (TASK-002) when all retries are exhausted.

Design decisions encoded in this module:

| Decision | Rationale |
|----------|-----------|
| Single-part `upload_from_string()` | Atomic — GCS either writes the whole object or fails; no partial objects |
| Date-partitioned path `{YYYY}/{MM}/{DD}/{msg_control_id}.hl7` | SC-3: date-range queries + lifecycle management (DR-006) |
| No PHI in GCS object metadata | BR-020: metadata is queryable by GCS admin; only `message_id` and `upload_timestamp` allowed |
| `asyncio`-aware via `run_in_executor` | GCS SDK is synchronous; offload to thread-pool so the asyncio MLLP handler is never blocked |
| CMEK bucket assumed pre-provisioned | Bucket created by Terraform (US-001); archiver only holds the bucket name from env var `HL7_ARCHIVE_BUCKET` |

Design refs: AIR-003, DR-015, BR-020, ADR-007, TR-005, US-013 DoD, SC-1, SC-3, SC-4.

---

## Acceptance Criteria Addressed

| US-013 AC | Requirement |
|---|---|
| **Scenario 1** | Raw HL7 text written to GCS before ACK is sent; `upload_from_string()` confirmed |
| **Scenario 3** | Archive path includes date partition: `{YYYY}/{MM}/{DD}/{msg_control_id}.hl7` |
| **Scenario 4** | Transient GCS error → 3 retries with exponential backoff (1 s, 2 s, 4 s); fallback called after all retries exhausted |
| **DoD** | `GCSArchiver` using `google-cloud-storage` SDK; no PHI in GCS object metadata |

---

## Implementation Steps

### 1. Scaffold the `archive` sub-package

```
hl7-listener/
└── app/
    └── archive/
        ├── __init__.py
        ├── gcs_archiver.py   ← THIS TASK
        └── fallback_queue.py ← TASK-002
```

```bash
mkdir -p hl7-listener/app/archive
touch hl7-listener/app/archive/__init__.py
```

### 2. Create `hl7-listener/app/archive/__init__.py`

```python
"""Archive sub-package — GCS raw HL7 message archival and fallback queue.

Exports:
  GCSArchiver       — async-capable GCS uploader with retry and fallback
  FallbackQueue     — bounded in-memory deque with background flush task

Design refs:
    AIR-003  — archive every raw HL7 message before ACK
    DR-015   — raw HL7 archive retention: 7 years, HIPAA bucket
    BR-020   — no PHI in GCS metadata
"""
from app.archive.gcs_archiver import GCSArchiver
from app.archive.fallback_queue import FallbackQueue

__all__ = ["GCSArchiver", "FallbackQueue"]
```

### 3. Create `hl7-listener/app/archive/gcs_archiver.py`

```python
"""GCS archiver for raw HL7 messages.

Writes each raw HL7 message as a single-part GCS object before the MLLP
ACK is dispatched.  Provides retry logic and delegates to ``FallbackQueue``
when all GCS retries are exhausted.

GCS object path format (SC-3 — date-partitioned):
    {YYYY}/{MM}/{DD}/{msg_control_id}.hl7

    Example: 2026/07/15/MSG-20260715-001.hl7

GCS object metadata (BR-020 — no PHI):
    message_id        — MSH-10 message control ID
    upload_timestamp  — ISO-8601 UTC datetime of upload attempt
    content_type      — text/plain

Retry policy (SC-4):
    3 attempts; delays: 1 s → 2 s → 4 s (exponential backoff, base=2).
    Uses ``asyncio.sleep`` so the event loop is not blocked between retries.

Environment variables:
    HL7_ARCHIVE_BUCKET — name of the pre-provisioned HIPAA CMEK GCS bucket

Design refs:
    AIR-003  — archive before ACK, path format
    DR-015   — 7-year retention, HIPAA CMEK bucket
    BR-020   — PHI must not appear in GCS metadata
    TR-005   — MLLP async event loop compatibility
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import TYPE_CHECKING

from google.cloud import storage
from google.api_core.exceptions import GoogleAPIError

if TYPE_CHECKING:
    from app.archive.fallback_queue import FallbackQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)  # seconds, exponential backoff
_CONTENT_TYPE = "text/plain"


# ---------------------------------------------------------------------------
# Path builder
# ---------------------------------------------------------------------------

def build_archive_path(msg_control_id: str, timestamp: datetime.datetime) -> str:
    """Return the date-partitioned GCS object path for a raw HL7 message.

    Format: ``{YYYY}/{MM}/{DD}/{msg_control_id}.hl7``

    Args:
        msg_control_id: MSH-10 value (e.g. ``"MSG-20260715-001"``).
        timestamp:      UTC datetime representing when the message arrived;
                        used to derive the date partition only.

    Returns:
        Object path string (no leading slash, no bucket prefix).

    Raises:
        ValueError: if ``msg_control_id`` is empty or ``None``.

    Example::

        >>> build_archive_path("MSG-001", datetime.datetime(2026, 7, 15))
        '2026/07/15/MSG-001.hl7'
    """
    if not msg_control_id or not msg_control_id.strip():
        raise ValueError("msg_control_id must be a non-empty string")
    dt = timestamp.astimezone(datetime.timezone.utc)
    return f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{msg_control_id.strip()}.hl7"


# ---------------------------------------------------------------------------
# GCSArchiver
# ---------------------------------------------------------------------------

class GCSArchiver:
    """Async-capable GCS archiver for raw HL7 messages.

    Wraps the synchronous ``google-cloud-storage`` SDK and offloads uploads
    to a thread-pool executor so the asyncio MLLP server is never blocked.

    Usage::

        archiver = GCSArchiver()
        archived = await archiver.archive(
            raw_hl7=raw_bytes,
            msg_control_id="MSG-001",
            arrived_at=datetime.datetime.now(datetime.timezone.utc),
        )

    Args:
        bucket_name:    GCS bucket name. Defaults to ``HL7_ARCHIVE_BUCKET``
                        environment variable.
        fallback_queue: ``FallbackQueue`` instance to receive messages when all
                        GCS retries are exhausted.  If ``None``, a warning is
                        logged and the message is dropped (not recommended for
                        production).
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        fallback_queue: "FallbackQueue | None" = None,
    ) -> None:
        self._bucket_name: str = bucket_name or os.environ["HL7_ARCHIVE_BUCKET"]
        self._fallback_queue = fallback_queue
        self._client: storage.Client | None = None  # lazy init; avoids auth in tests

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def archive(
        self,
        raw_hl7: str,
        msg_control_id: str,
        arrived_at: datetime.datetime,
    ) -> bool:
        """Archive a raw HL7 message to GCS.

        This coroutine must be awaited **before** the MLLP ACK is sent (SC-1).
        It returns ``True`` when the GCS object is successfully written, or
        ``False`` when all retries failed and the message was queued in the
        fallback queue.

        Args:
            raw_hl7:        The raw HL7 message text (MLLP framing already
                            stripped).
            msg_control_id: MSH-10 message control ID.
            arrived_at:     UTC datetime of MLLP message receipt.

        Returns:
            ``True`` on GCS success; ``False`` if fallback queue was used.
        """
        object_path = build_archive_path(msg_control_id, arrived_at)
        metadata = {
            "message_id": msg_control_id,
            "upload_timestamp": arrived_at.astimezone(datetime.timezone.utc).isoformat(),
        }
        # Attempt upload with retry
        loop = asyncio.get_event_loop()
        last_exc: Exception | None = None

        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            try:
                await loop.run_in_executor(
                    None,
                    self._upload_sync,
                    raw_hl7,
                    object_path,
                    metadata,
                )
                logger.info(
                    "HL7 message archived to GCS",
                    extra={
                        "gcs_path": f"gs://{self._bucket_name}/{object_path}",
                        "message_id": msg_control_id,
                        "attempt": attempt,
                    },
                )
                return True
            except (GoogleAPIError, OSError) as exc:
                last_exc = exc
                logger.warning(
                    "GCS archive attempt %d failed for message_id=%s: %s",
                    attempt,
                    msg_control_id,
                    type(exc).__name__,
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(delay)

        # All retries exhausted — delegate to fallback queue
        logger.error(
            "All GCS archive retries exhausted for message_id=%s; routing to fallback queue",
            msg_control_id,
        )
        await self._enqueue_fallback(raw_hl7, msg_control_id, arrived_at, last_exc)
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> storage.Client:
        """Lazy-initialise the GCS client (allows mocking in tests)."""
        if self._client is None:
            self._client = storage.Client()
        return self._client

    def _upload_sync(
        self,
        raw_hl7: str,
        object_path: str,
        metadata: dict[str, str],
    ) -> None:
        """Synchronous GCS upload — run in executor to avoid blocking event loop.

        Sets custom metadata (message_id, upload_timestamp) but never includes
        PHI values (BR-020).
        """
        client = self._get_client()
        bucket = client.bucket(self._bucket_name)
        blob = bucket.blob(object_path)
        blob.metadata = metadata
        blob.upload_from_string(
            data=raw_hl7,
            content_type=_CONTENT_TYPE,
        )

    async def _enqueue_fallback(
        self,
        raw_hl7: str,
        msg_control_id: str,
        arrived_at: datetime.datetime,
        exc: Exception | None,
    ) -> None:
        """Push message to fallback queue and fire alert metric."""
        if self._fallback_queue is not None:
            await self._fallback_queue.enqueue(raw_hl7, msg_control_id, arrived_at)
        else:
            logger.critical(
                "No fallback queue configured — raw HL7 message DROPPED for message_id=%s. "
                "Configure FallbackQueue to prevent message loss.",
                msg_control_id,
            )
        # Emit alert metric for Cloud Monitoring (TR-015 / SC-4)
        _emit_archive_failure_metric(msg_control_id, exc)


def _emit_archive_failure_metric(msg_control_id: str, exc: Exception | None) -> None:
    """Log a structured alert for Cloud Monitoring to pick up as a custom metric.

    In production this structured log entry is parsed by a Cloud Monitoring
    log-based metric (``hl7_archive_failure_count``), triggering a P1 alert.
    """
    logger.error(
        "hl7_archive_failure",
        extra={
            "event": "hl7_archive_failure",
            "message_id": msg_control_id,
            "error_type": type(exc).__name__ if exc else "Unknown",
        },
    )
```

### 4. Add `google-cloud-storage` to `hl7-listener/requirements.txt`

```
google-cloud-storage>=2.17.0
```

---

## File Structure After This Task

```
hl7-listener/
└── app/
    └── archive/
        ├── __init__.py          ← exports GCSArchiver, FallbackQueue
        └── gcs_archiver.py      ← GCSArchiver, build_archive_path ← THIS TASK
```

---

## Definition of Done Checklist (this task)

- [ ] `build_archive_path()` returns `{YYYY}/{MM}/{DD}/{msg_control_id}.hl7` format
- [ ] `GCSArchiver.archive()` calls `upload_from_string()` before returning
- [ ] Retry attempts: exactly 3, delays 1 s / 2 s / 4 s
- [ ] GCS object metadata contains only `message_id` and `upload_timestamp` (no PHI)
- [ ] `run_in_executor` used for the synchronous GCS SDK call
- [ ] `FallbackQueue.enqueue()` called and `_emit_archive_failure_metric()` logged after all retries exhausted
- [ ] `google-cloud-storage>=2.17.0` added to `requirements.txt`
