---
id: TASK-006
title: "Code Review & DoD Sign-off — US-014 Pub/Sub Publisher & Ordering"
user_story: US-014
epic: EP-001
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-014/TASK-001, US-014/TASK-002, US-014/TASK-003, US-014/TASK-004, US-014/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-014 Pub/Sub Publisher & Ordering

> **Story:** US-014 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-014. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story. Three high-risk surfaces require security sign-off:

1. **PHI in Pub/Sub message attributes (BR-020):** The `patient_mrn_hash` attribute must be a SHA-256 hex digest of the MRN — never the raw MRN. Pub/Sub message attributes are accessible in GCP Cloud Console and Cloud Logging without application-layer decryption; raw PHI here constitutes a HIPAA violation.

2. **PHI in Pub/Sub message body (ADR-007):** The message body contains the full `ADTEvent` JSON. Confirm that PHI fields (`first_name`, `last_name`, `dob`, `mrn`) are stored as ciphertext (AES-256-GCM encrypted via `SQLAlchemy TypeDecorator`) in the `ADTEvent` model's JSON serialisation — not as plaintext strings.

3. **Ordering key exposure (OWASP A03 — Information Disclosure):** The ordering key = `encounter_id` (UUID). Confirm this is non-guessable (UUID v4) and does not encode or expose PHI.

Review focus areas beyond standard code quality:

1. **`enable_message_ordering=True` in `PublisherOptions`** — confirm this is set on the `PublisherClient` constructor, not just on the subscription. Without this, ordering keys are silently ignored.
2. **SHA-256 hash of MRN in attributes** — confirm `hashlib.sha256(str(mrn).encode("utf-8")).hexdigest()` is used; confirm no `patient.first_name`, `patient.last_name`, `patient.dob`, or `patient.mrn` plaintext in attributes.
3. **Retry count = 3** — confirm `_RETRY_DELAYS == (1.0, 2.0, 4.0)` (exactly 3 delays).
4. **`run_in_executor` for sync SDK call** — confirm `_sync_publish()` is dispatched via `loop.run_in_executor()`, not called directly (which would block the event loop).
5. **`publish()` called after `router.route()`** — confirm step 6 (publish) follows step 5 (route/persist) in `pipeline.py`; an `assert` or source order check in unit tests is sufficient.
6. **`PublishRetryQueue.start()` in lifespan startup** — confirm background flush task is created before the first MLLP connection is accepted.
7. **`publisher.close()` and `retry_queue.stop()` in lifespan shutdown** — confirm both are `await`ed in the SIGTERM handler (TR-017).
8. **Bounded retry queue** — confirm `deque(maxlen=200)` is used; no unbounded accumulation risk.

---

## Pre-Review Validation Sequence

Run all checks from the `hl7-listener/` directory before requesting review:

```bash
cd hl7-listener

# -----------------------------------------------------------------------
# 1. Install dependencies
# -----------------------------------------------------------------------
pip install -r requirements.txt

# -----------------------------------------------------------------------
# 2. Syntax check — all new modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
targets = [
    'app/pubsub/__init__.py',
    'app/pubsub/adt_event_publisher.py',
    'app/pubsub/publish_retry_queue.py',
    'app/mllp/pipeline.py',
]
for p in targets:
    ast.parse(pathlib.Path(p).read_text())
    print(f'  {p}: OK')
print('Syntax check: PASSED')
"

# -----------------------------------------------------------------------
# 3. Import check — all public symbols
# -----------------------------------------------------------------------
python -c "
from app.pubsub import ADTEventPublisher, PublishRetryQueue
from app.pubsub.adt_event_publisher import _build_attributes, _RETRY_DELAYS
print('Import check: PASSED')
"

# -----------------------------------------------------------------------
# 4. Verify enable_message_ordering is set
# -----------------------------------------------------------------------
python -c "
import inspect
from app.pubsub.adt_event_publisher import ADTEventPublisher
src = inspect.getsource(ADTEventPublisher.__init__)
assert 'enable_message_ordering=True' in src, \
    'enable_message_ordering=True not found in ADTEventPublisher.__init__'
print('enable_message_ordering: PASSED')
"

# -----------------------------------------------------------------------
# 5. Verify retry delays = (1.0, 2.0, 4.0)
# -----------------------------------------------------------------------
python -c "
from app.pubsub.adt_event_publisher import _RETRY_DELAYS
assert _RETRY_DELAYS == (1.0, 2.0, 4.0), f'Expected (1.0, 2.0, 4.0), got {_RETRY_DELAYS}'
print(f'Retry delays: {_RETRY_DELAYS} — PASSED')
"

# -----------------------------------------------------------------------
# 6. Verify SHA-256 MRN hash in _build_attributes (no raw MRN)
# -----------------------------------------------------------------------
python -c "
import hashlib, inspect
from app.pubsub.adt_event_publisher import _build_attributes
src = inspect.getsource(_build_attributes)
assert 'sha256' in src, 'SHA-256 hash not found in _build_attributes'
assert 'patient.mrn' in src or 'mrn' in src, 'MRN reference not found in _build_attributes'
# No format string or f-string concatenation of mrn directly into attribute value
assert 'f\"' not in src or 'mrn_hash' in src, \
    'Possible raw MRN f-string detected in _build_attributes'
print('SHA-256 MRN hash construction: PASSED')
"

# -----------------------------------------------------------------------
# 7. Verify run_in_executor is used for sync SDK call
# -----------------------------------------------------------------------
python -c "
import inspect
from app.pubsub.adt_event_publisher import ADTEventPublisher
src = inspect.getsource(ADTEventPublisher._publish_once)
assert 'run_in_executor' in src, 'run_in_executor not found in _publish_once'
print('run_in_executor usage: PASSED')
"

# -----------------------------------------------------------------------
# 8. Verify publish step follows route step in pipeline
# -----------------------------------------------------------------------
python -c "
import inspect
from app.mllp.pipeline import MLLPPipeline
src = inspect.getsource(MLLPPipeline.process_message)
route_pos = src.index('router.route')
publish_pos = src.index('publisher.publish')
assert publish_pos > route_pos, 'publish() must come after route() in pipeline'
print('Pipeline step order (route < publish): PASSED')
"

# -----------------------------------------------------------------------
# 9. Verify bounded retry queue (maxlen=200)
# -----------------------------------------------------------------------
python -c "
from app.pubsub.publish_retry_queue import _MAX_QUEUE_SIZE
assert _MAX_QUEUE_SIZE == 200, f'Expected 200, got {_MAX_QUEUE_SIZE}'
print(f'Retry queue max size: {_MAX_QUEUE_SIZE} — PASSED')
"

# -----------------------------------------------------------------------
# 10. Run unit tests
# -----------------------------------------------------------------------
pytest tests/unit/pubsub/ -v --tb=short

# -----------------------------------------------------------------------
# 11. Coverage gate (≥80%)
# -----------------------------------------------------------------------
pytest tests/unit/pubsub/ \
  --cov=app/pubsub \
  --cov-report=term-missing \
  --cov-fail-under=80

echo "=== All pre-review checks PASSED ==="
```

---

## Code Review Checklist

### Security (Mandatory — Security Engineer sign-off required)

- [ ] `patient_mrn_hash` in attributes is `SHA-256(mrn)` — raw MRN never present
- [ ] PHI fields in `ADTEvent` JSON body are ciphertext (encrypted by `TypeDecorator`) — not plaintext
- [ ] `encounter_id` ordering key is UUID v4 — non-guessable, no PHI encoded
- [ ] No PHI in any structured log field (`encounter_id`, `event_type`, `queue_depth` only)
- [ ] `publisher.publish()` never logs message body or attributes to Cloud Logging

### Functionality

- [ ] `PublisherOptions(enable_message_ordering=True)` set on `PublisherClient`
- [ ] Ordering key = `str(event.encounter_id)` on every `_sync_publish` call
- [ ] `_RETRY_DELAYS == (1.0, 2.0, 4.0)` — exactly 3 attempts
- [ ] `run_in_executor` used for blocking `future.result()` call
- [ ] `publish()` called after `router.route()` in `pipeline.py`
- [ ] ACK returned only after `publish()` returns (not before)
- [ ] `PublishRetryQueue.start()` called in FastAPI lifespan startup
- [ ] `PublishRetryQueue.stop()` called in FastAPI lifespan shutdown
- [ ] `publisher.close()` called in FastAPI lifespan shutdown

### Test Coverage

- [ ] All 4 acceptance criteria scenarios covered by unit tests
- [ ] Integration test with Pub/Sub emulator passes (FIFO A01 → A02 → A03)
- [ ] `pytest --cov=app/pubsub --cov-fail-under=80` passes
- [ ] BR-020 PHI assertion in integration test (`raw_mrn not in attributes`)

### Infrastructure

- [ ] Terraform `enable_message_ordering = true` set on all `adt-events` subscriptions (US-001/Terraform) — note in PR if not yet provisioned
- [ ] `PUBSUB_PROJECT_ID` and `PUBSUB_TOPIC_ID` env vars documented in Cloud Run service config (Terraform)

---

## US-014 Definition of Done — Final Checklist

- [ ] `ADTEventPublisher` class wraps `google.cloud.pubsub_v1.PublisherClient` with ordering key support
- [ ] `ADTEvent` Pydantic model serialises to JSON for Pub/Sub message body
- [ ] Pub/Sub message attributes: `event_type`, `encounter_id`, `patient_mrn_hash`, `iso_timestamp`
- [ ] Ordering key = `encounter_id` (string) set on every `PublishRequest`
- [ ] Publisher retry: 3 attempts, exponential backoff (1s, 2s, 4s); Prometheus counter `pubsub_publish_failures_total`
- [ ] Unit tests: verify message body schema, ordering key, attribute presence
- [ ] Integration test: publish and pull from test subscription confirms FIFO order for same encounter
- [ ] Code reviewed and approved (Backend Engineer + Security Engineer)
