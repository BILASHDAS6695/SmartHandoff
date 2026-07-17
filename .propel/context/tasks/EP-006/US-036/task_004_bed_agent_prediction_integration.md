---
id: TASK-004
title: "BedManagementAgent — Discharge Prediction Integration and Encounter Update"
user_story: US-036
epic: EP-006
sprint: 2
layer: Backend / AI Agent
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-036/TASK-001, US-036/TASK-002, US-036/TASK-003, US-035/TASK-001]
---

# TASK-004: BedManagementAgent — Discharge Prediction Integration and Encounter Update

> **Story:** US-036 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-036 AC Scenario 3 requires that the `predicted_discharge_time` on the bed board be **updated within 60 seconds** whenever a patient's status changes. The `BedManagementAgent` (US-035/TASK-001) is the natural integration point: after completing a bed status transition for an A01/A02/A03 event, it should additionally call the ML Inference Service, store the prediction on the encounter record, and trigger a materialised view refresh.

This task extends `BedManagementAgent` with a `DischargePredictionService` that:
1. Builds the feature vector from the encounter record.
2. POSTs to `POST /ml-inference/predict/discharge-time` with a service-account-authenticated HTTP call.
3. Writes the returned `predicted_discharge_time`, `discharge_prediction_confidence`, and `discharge_prediction_interval_hours` back to the `encounter` row.
4. Re-triggers `BedBoardRefreshService.refresh_async()` so the updated prediction appears in `mv_bed_board` within 60 seconds.

**Design references:**
- US-036 AC Scenario 3 — prediction updated within 60 s of status change
- US-036 Technical Notes — feature derivation; confidence thresholds
- design.md §3.2 — Agent tool set: `DB`, `API` calls are agent tools
- design.md §5.1 (TR-007) — ML inference latency <500 ms (inference service handles this)
- AIR-011 — async HTTP client (httpx); exponential backoff (3 attempts, 1 s/2 s/4 s)
- ADR-004 — Pydantic structured output; LangChain agent framework

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Feature vector construction produces correct input for the inference service |
| Scenario 3 | `predicted_discharge_time` on bed board updated within 60 s of status change |

---

## Implementation Steps

### 1. Create `backend/app/agents/bed_management/prediction_service.py`

```python
"""DischargePredictionService — calls the ML Inference Service and persists the result.

Called by BedManagementAgent after every successful bed status transition to
update encounter.predicted_discharge_time (US-036 AC Scenario 3).

Design refs:
    US-036 AC Scenario 3 — update within 60 s of status change
    AIR-011              — httpx async client; 3-attempt exponential backoff; circuit breaker
    TR-007               — <500 ms inference latency (enforced by inference service)
    ADR-007              — no PHI in logs (encounter_id UUID only)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.agents.bed_management.schemas import ConfidenceLevel

logger = logging.getLogger(__name__)

ML_INFERENCE_BASE_URL = os.environ.get("ML_INFERENCE_SERVICE_URL", "http://ml-inference")
ML_INFERENCE_ENDPOINT = "/ml-inference/predict/discharge-time"
_BACKOFF_DELAYS = (1.0, 2.0, 4.0)  # AIR-011: 3-attempt exponential backoff


class DischargePredictionService:
    """Fetches a discharge time prediction and persists it to the encounter record.

    Args:
        http_client: ``httpx.AsyncClient`` configured with service account ID token auth.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def update_prediction(
        self,
        session: AsyncSession,
        encounter_id: str,
        refresh_service: Any,
    ) -> bool:
        """Fetch prediction for ``encounter_id`` and update the encounter row.

        Args:
            session: Active write ``AsyncSession`` (called outside the main transaction).
            encounter_id: UUID of the encounter to update.
            refresh_service: ``BedBoardRefreshService`` to trigger after the DB write.

        Returns:
            ``True`` if prediction was successfully written; ``False`` on non-retryable failure.
        """
        encounter = await self._fetch_encounter(session, encounter_id)
        if encounter is None:
            logger.warning("Encounter not found for prediction: %s", encounter_id)
            return False

        payload = self._build_request_payload(encounter, encounter_id)
        prediction = await self._call_inference_service(payload, encounter_id)
        if prediction is None:
            return False

        await session.execute(
            update(Encounter)
            .where(Encounter.id == encounter.id)
            .values(
                predicted_discharge_time=prediction["predicted_discharge_time"],
                discharge_prediction_confidence=prediction["confidence_level"],
                discharge_prediction_interval_hours=prediction["confidence_interval_hours"],
            )
        )
        await session.commit()

        # Refresh mv_bed_board so the new prediction appears within 60 s (AC Scenario 3)
        await refresh_service.refresh_async()

        logger.info(
            "Prediction stored: encounter_id=%s predicted=%s confidence=%s",
            encounter_id,
            prediction["predicted_discharge_time"].isoformat(),
            prediction["confidence_level"],
        )
        return True

    def _build_request_payload(self, encounter: Encounter, encounter_id: str) -> dict:
        """Construct the JSON payload for the ML Inference Service request.

        Uses ``encounter`` ORM object fields. ``patient_dob`` is retrieved from
        the related ``patient`` record (must be eagerly loaded or fetched separately).

        Note: PHI fields (patient_dob) are passed only to the inference service
        over the internal VPC; they are NOT logged anywhere (ADR-007 / BR-020).
        """
        return {
            "encounter_id": encounter_id,
            "admit_time": encounter.admit_time.isoformat(),
            "patient_dob": encounter.patient.dob.isoformat(),
            "admit_diagnosis_group": encounter.admit_diagnosis_group or "UNKNOWN",
            "unit": encounter.unit or "UNKNOWN",
            "pending_procedures_count": encounter.pending_procedures_count or 0,
        }

    async def _fetch_encounter(self, session: AsyncSession, encounter_id: str) -> Encounter | None:
        """Load encounter with joined patient (for DOB) from the write DB."""
        from sqlalchemy.orm import selectinload
        import uuid

        result = await session.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))
            .where(Encounter.id == uuid.UUID(encounter_id))
            .where(Encounter.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def _call_inference_service(
        self,
        payload: dict,
        encounter_id: str,
    ) -> dict | None:
        """POST to the ML Inference Service with exponential backoff.

        Returns parsed response dict or ``None`` on exhausted retries.
        PHI fields in ``payload`` are not logged.
        """
        url = f"{ML_INFERENCE_BASE_URL}{ML_INFERENCE_ENDPOINT}"

        for attempt, delay in enumerate(_BACKOFF_DELAYS, start=1):
            try:
                resp = await self._http.post(url, json=payload, timeout=5.0)
                resp.raise_for_status()
                data = resp.json()
                return {
                    "predicted_discharge_time": datetime.fromisoformat(
                        data["predicted_discharge_time"]
                    ).replace(tzinfo=timezone.utc),
                    "confidence_level": data["confidence_level"],
                    "confidence_interval_hours": data["confidence_interval_hours"],
                }
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning(
                    "ML Inference call failed (attempt %d/%d) encounter_id=%s: %s",
                    attempt,
                    len(_BACKOFF_DELAYS),
                    encounter_id,
                    type(exc).__name__,
                )
                if attempt < len(_BACKOFF_DELAYS):
                    await asyncio.sleep(delay)

        logger.error(
            "ML Inference Service unreachable after %d attempts for encounter_id=%s. "
            "Prediction will not be updated this cycle.",
            len(_BACKOFF_DELAYS),
            encounter_id,
        )
        return None
```

### 2. Extend `BedManagementAgent.process()` to call `DischargePredictionService`

Modify `backend/app/agents/bed_management/agent.py` — extend `process()` post-commit:

```python
# After the existing post-commit side effects block in process():

# Trigger discharge time prediction update (AC Scenario 3)
# Called outside the main bed-status transaction so a prediction failure
# never rolls back the bed status write.
if self._prediction_service is not None and event_type in ("A01", "A02", "A03"):
    async with self._db_session_factory() as pred_session:
        await self._prediction_service.update_prediction(
            session=pred_session,
            encounter_id=encounter_id,
            refresh_service=self._refresh_service,
        )
```

Also update `__init__` signature to accept the prediction service:

```python
def __init__(
    self,
    db_session_factory: Any,
    refresh_service: Any,
    housekeeping_notifier: Any,
    prediction_service: Any | None = None,   # NEW — optional for backward compatibility
) -> None:
    super().__init__(subscription_id="bed-mgmt-agent-sub")
    self._db_session_factory = db_session_factory
    self._refresh_service = refresh_service
    self._housekeeping_notifier = housekeeping_notifier
    self._prediction_service = prediction_service  # NEW
```

### 3. Wire `DischargePredictionService` in the Cloud Run entrypoint

Update `backend/app/agents/bed_management/main.py`:

```python
import httpx
import google.auth
import google.auth.transport.requests
from app.agents.bed_management.prediction_service import DischargePredictionService

# Build authenticated httpx client using Google Application Default Credentials
def _build_authenticated_http_client() -> httpx.AsyncClient:
    """Create an httpx.AsyncClient that sends a service account ID token on each request."""
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)

    class _GoogleAuthTransport(httpx.AsyncBaseTransport):
        """Injects Bearer token from refreshed credentials."""
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            credentials.refresh(auth_req)
            request.headers["Authorization"] = f"Bearer {credentials.token}"
            return await httpx.AsyncClient().send(request)

    return httpx.AsyncClient(transport=_GoogleAuthTransport())


async def main() -> None:
    refresh_service = BedBoardRefreshService()
    housekeeping_notifier = HousekeepingNotifier(pubsub_client=get_pubsub_client())
    http_client = _build_authenticated_http_client()
    prediction_service = DischargePredictionService(http_client=http_client)

    agent = BedManagementAgent(
        db_session_factory=get_write_db,
        refresh_service=refresh_service,
        housekeeping_notifier=housekeeping_notifier,
        prediction_service=prediction_service,
    )
    await agent.run()
```

### 4. Add `ML_INFERENCE_SERVICE_URL` environment variable to Cloud Run config

In Terraform `bed-mgmt-agent` Cloud Run service (reference — implemented in infra-spec):

```hcl
env {
  name  = "ML_INFERENCE_SERVICE_URL"
  value = "https://ml-inference-<hash>-uc.a.run.app"
}
```

Also add to `backend/app/agents/bed_management/main.py` startup validation:

```python
import os
if not os.environ.get("ML_INFERENCE_SERVICE_URL"):
    logger.warning(
        "ML_INFERENCE_SERVICE_URL not set — discharge predictions will be skipped."
    )
```

---

## Validation Checklist

- [ ] After A01 event for an ADMITTED encounter, `encounter.predicted_discharge_time` is set within 60 seconds
- [ ] After A03 event, prediction is still updated (useful for historical analysis of actual vs predicted)
- [ ] `mv_bed_board` reflects the updated `predicted_discharge_time` within 60 s of the event
- [ ] A failed ML Inference call (503) does NOT cause the bed status transition to roll back
- [ ] Backoff: on ML Inference 503, the agent retries 3 times before giving up (sleep 1 s, 2 s)
- [ ] No PHI fields (name, MRN, DOB) appear in application logs for this service
- [ ] `encounter_id` (UUID) used as the sole log correlation key
- [ ] `ML_INFERENCE_SERVICE_URL` env var unset → prediction skipped with WARNING log (not crash)

---

## Definition of Done Checklist (US-036)

| Item | Status |
|------|--------|
| ✅ Prediction stored in `encounter.predicted_discharge_time` and reflected in `mv_bed_board` | This task |
| ✅ Prediction updates when patient status changes (AC Scenario 3) | This task |
