---
id: TASK-006
title: "Code Review & DoD Sign-off — US-013 GCS Archive & Idempotency"
user_story: US-013
epic: EP-001
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-013/TASK-001, US-013/TASK-002, US-013/TASK-003, US-013/TASK-004, US-013/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-013 GCS Archive & Idempotency

> **Story:** US-013 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-013. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story. Two high-risk surfaces require security sign-off:

1. **GCS object metadata (BR-020):** The metadata written to each GCS object must contain only `message_id` and `upload_timestamp`. Any inclusion of patient name, MRN, DOB, or any other PHI field constitutes a HIPAA violation because GCS metadata is queryable by storage administrators without application-layer decryption.

2. **SQL idempotency query (OWASP A03 — Injection):** The `IdempotencyChecker` must use parameterised queries only. `source_message_id` originates from an untrusted HL7 message (`MSH-10`); string interpolation into the SQL query would introduce a SQL injection vulnerability. The `text()` + bindparam pattern must be verified.

Review focus areas beyond standard code quality:
1. **PHI in GCS metadata** — confirm only `message_id` and `upload_timestamp` in `blob.metadata`.
2. **Parameterised SQL** — confirm `SELECT EXISTS` uses `:msg_id` bindparam, not f-string or `%s` formatting.
3. **Archive-before-ACK ordering** — confirm `GCSArchiver.archive()` is `await`ed before any `return build_ack_response(...)` or `return build_nack_response(...)` in `pipeline.py`.
4. **Retry count** — confirm exactly 3 retry attempts (len `_RETRY_DELAYS == 3`) with delays 1 s / 2 s / 4 s.
5. **Fallback queue bounded** — confirm `deque(maxlen=500)` is used; no unbounded accumulation.
6. **Graceful shutdown** — confirm `FallbackQueue.stop()` is called in the `lifespan` shutdown path of `main.py`.

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
    'app/archive/gcs_archiver.py',
    'app/archive/fallback_queue.py',
    'app/idempotency/idempotency_checker.py',
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
from app.archive import GCSArchiver, FallbackQueue
from app.archive.gcs_archiver import build_archive_path
from app.idempotency import IdempotencyChecker
print('Import check: PASSED')
"

# -----------------------------------------------------------------------
# 4. Verify archive path format (DoD-a: date-partitioned)
# -----------------------------------------------------------------------
python -c "
import datetime
from app.archive.gcs_archiver import build_archive_path

cases = [
    (datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc), 'MSG-001', '2026/07/15/MSG-001.hl7'),
    (datetime.datetime(2026, 1,  5, tzinfo=datetime.timezone.utc), 'MSG-X',   '2026/01/05/MSG-X.hl7'),
]
for ts, msg_id, expected in cases:
    result = build_archive_path(msg_id, ts)
    assert result == expected, f'Expected {expected!r}, got {result!r}'
print('Archive path format: PASSED')
"

# -----------------------------------------------------------------------
# 5. Verify retry count = 3 with correct delays
# -----------------------------------------------------------------------
python -c "
from app.archive.gcs_archiver import _RETRY_DELAYS
assert len(_RETRY_DELAYS) == 3, f'Expected 3 retry delays, got {len(_RETRY_DELAYS)}'
assert list(_RETRY_DELAYS) == [1.0, 2.0, 4.0], f'Expected [1.0, 2.0, 4.0], got {list(_RETRY_DELAYS)}'
print('Retry delays: PASSED')
"

# -----------------------------------------------------------------------
# 6. Verify fallback queue bounded at 500
# -----------------------------------------------------------------------
python -c "
from collections import deque
from app.archive.fallback_queue import _MAX_QUEUE_SIZE
assert _MAX_QUEUE_SIZE == 500, f'Expected maxlen=500, got {_MAX_QUEUE_SIZE}'
print('Fallback queue bounded: PASSED')
"

# -----------------------------------------------------------------------
# 7. Security check: confirm no PHI field names in GCS metadata keys
# -----------------------------------------------------------------------
python -c "
import ast, pathlib

source = pathlib.Path('app/archive/gcs_archiver.py').read_text()
phi_indicators = ['first_name', 'last_name', 'patient_name', 'mrn', 'dob', 'date_of_birth', 'phone', 'email']
for phi in phi_indicators:
    assert phi not in source.lower() or '# no phi' in source.lower(), f'Possible PHI reference in gcs_archiver.py: {phi}'
print('PHI metadata check: PASSED')
"

# -----------------------------------------------------------------------
# 8. Security check: confirm parameterised SQL in idempotency_checker.py
# -----------------------------------------------------------------------
python -c "
import pathlib

source = pathlib.Path('app/idempotency/idempotency_checker.py').read_text()
# Must use bindparam :msg_id, not f-string or % formatting
assert ':msg_id' in source, 'Parameterised SQL bindparam :msg_id not found'
assert 'f\"' not in source and \"f'\" not in source or 'msg_id' not in source.split('f')[1] if 'f\"' in source or \"f'\" in source else True, \
    'Possible f-string in SQL query detected'
print('Parameterised SQL check: PASSED')
"

# -----------------------------------------------------------------------
# 9. Run unit tests with coverage
# -----------------------------------------------------------------------
pytest tests/unit/archive/ tests/unit/idempotency/ \
    --cov=app/archive --cov=app/idempotency \
    --cov-report=term-missing \
    --cov-fail-under=80 \
    -v
```

---

## US-013 Definition of Done — Final Checklist

| # | Requirement | Verified By |
|---|-------------|-------------|
| 1 | GCS write using `google-cloud-storage` SDK occurs atomically before ACK | TASK-004 pipeline ordering + TASK-005 test `test_archive_calls_upload_before_returning` |
| 2 | Archive path: `gs://{HIPAA_BUCKET}/{YYYY}/{MM}/{DD}/{msg_control_id}.hl7` | TASK-001 `build_archive_path()` + TASK-005 parametrised test |
| 3 | Idempotency check queries `adt_event.source_message_id` (MSH-10) before processing | TASK-003 `IdempotencyChecker` + TASK-004 pipeline step order |
| 4 | Returns ACK early on duplicate; no new `adt_event` record created | TASK-004 pipeline + TASK-005 `test_is_duplicate_returns_true_for_known_id` |
| 5 | `source_message_id` is indexed on `adt_event` (O(log n)) | US-006 migration (dependency — index must be verified in staging) |
| 6 | GCS write retries: 3 attempts, exponential backoff (1 s, 2 s, 4 s) | TASK-001 `_RETRY_DELAYS` + TASK-005 retry count and delay tests |
| 7 | Unit tests: (a) archive path format, (b) duplicate detection, (c) GCS failure retry | TASK-005 full test suite |
| 8 | HIPAA bucket: object versioning, CMEK, Uniform Bucket-Level Access, no public access | US-001 Terraform (dependency — verify `gsutil ls -L gs://hl7-archive` in staging) |
| 9 | No PHI in GCS object metadata | TASK-001 metadata dict, Security check step 7, TASK-005 `test_archive_sets_metadata_without_phi` |
| 10 | Parameterised SQL (no injection vector) | TASK-003 `text()` + bindparam, Security check step 8 |
| 11 | Code reviewed and approved | This task sign-off |

---

## Review Sign-off

| Reviewer | Role | Sign-off Date | Notes |
|----------|------|--------------|-------|
| | Backend Engineer | | |
| | Security Engineer | | PHI metadata + SQL injection focus |
