---
id: TASK-006
title: "Code Review & DoD Sign-off — US-011 MLLP TCP Listener"
user_story: US-011
epic: EP-001
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-011/TASK-001, US-011/TASK-002, US-011/TASK-003, US-011/TASK-004, US-011/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-011 MLLP TCP Listener

> **Story:** US-011 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-011. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A Security Engineer review is recommended due to the PHI-adjacent nature of the HL7 ingestion path (all ADT messages contain patient demographics). While the MLLP listener does not persist data, it is the first point of PHI contact in the system.

---

## Pre-Review Checklist

Run the full validation sequence before requesting review:

```bash
cd hl7-listener

# 1. Install all dependencies
pip install -r requirements.txt

# 2. Syntax / import check for all modules
python -c "
import ast, pathlib
for p in pathlib.Path('app').rglob('*.py'):
    ast.parse(p.read_text())
    print(f'  {p}: OK')
print('Syntax check: PASSED')
"

# 3. Verify framing module
python -c "
from app.mllp.framing import extract_hl7_message, wrap_hl7_message, MllpFramingError
frame = wrap_hl7_message(b'MSH|^~\&|EHR|HOSP|||20260715||ADT^A01|MSG001|P|2.5\r')
assert extract_hl7_message(frame) == b'MSH|^~\&|EHR|HOSP|||20260715||ADT^A01|MSG001|P|2.5\r'
print('framing.py roundtrip: PASSED')
"

# 4. Verify ACK builder
python -c "
from app.mllp.ack_builder import build_ack_response, build_nack_response
hl7 = 'MSH|^~\&|EHR|HOSP|SmartHandoff|HOSP|20260715||ADT^A01|MSG001|P|2.5\rEVN|A01|\rPID|1\r'
ack = build_ack_response(hl7)
assert b'MSA|AA|MSG001' in ack, 'ACK MSA check failed'
nack = build_nack_response(hl7, 'Test error')
assert b'MSA|AE|MSG001' in nack and b'207' in nack, 'NACK check failed'
print('ack_builder.py: PASSED')
"

# 5. Run unit tests with coverage
pytest tests/unit/mllp/ -v \
  --cov=app/mllp/framing \
  --cov=app/mllp/ack_builder \
  --cov-report=term-missing \
  --cov-fail-under=80

# 6. SAST scan — no HIGH or CRITICAL issues
pip install bandit
bandit -r app/ -ll --skip B101
# B101 (assert usage) is skipped — asserts are only in test helpers, not production paths

# 7. Confirm PHI never appears in log statements
grep -rn "first_name\|last_name\|dob\|phone\|email\|date_of_birth" app/ \
  --include="*.py" \
  | grep -v "^app/mllp/ack_builder.py.*error_text" \
  | grep "logger\."
# Expected: no matches (any matches indicate potential PHI in logs)
```

---

## Code Review Checklist

### Security Review (Security Engineer — Recommended)

- [ ] `MllpFramingError` and `ValueError` caught in connection handler — no unhandled exceptions expose stack traces to the EHR client
- [ ] Error text in NACK ERR-8 (`error_text` param) does not include PHI field names or values — verified by grep above
- [ ] `error_text[:200]` truncation in `build_nack_response` prevents oversized ERR segments
- [ ] `MAX_MESSAGE_SIZE = 1_048_576` (1 MB) cap prevents memory exhaustion via oversized frames
- [ ] `READ_BUFFER_SIZE = 65536` (64 KB) per-read cap prevents single-read memory spike
- [ ] No hardcoded credentials, ports, or hostnames in production code paths — all via env vars (`MLLP_PORT`, `HEALTH_PORT`)
- [ ] `SO_KEEPALIVE` socket options use `hasattr` guards — no crash on platforms that lack `TCP_KEEPIDLE` / `TCP_KEEPINTVL`
- [ ] `python:3.12-slim` base image used in Dockerfile (TR-019: minimal attack surface)
- [ ] `--no-cache-dir` on `pip install` in Dockerfile (prevents sensitive pip cache in layer)

### Functional Review (Peer Engineer)

- [ ] `MLLP_START = b'\x0b'` and `MLLP_END = b'\x1c\x0d'` constants match MLLP specification
- [ ] `asyncio.Semaphore(50)` released in `finally` block — no semaphore leak on exception
- [ ] `asyncio.wait_for(PARSE_TIMEOUT_S=0.18)` wraps only the HL7 parse step, not the full connection lifecycle
- [ ] `read_mllp_frame` handles multi-frame buffers correctly (second call on remainder yields second frame)
- [ ] ACK MSA-2 echoes the inbound MSH-10 verbatim (control ID round-trip verified by tests)
- [ ] NACK ERR code `207` used for all application-level failures (per AIR-001)
- [ ] `asyncio.gather` in `main.py` runs MLLP server and health server concurrently in the same event loop
- [ ] Health server returns `200` for both `/health` and `/ready`; Prometheus `/metrics` returns text format
- [ ] `hl7apy` parse is run via `run_in_executor` — CPU-bound parsing does not block the event loop
- [ ] All Prometheus metrics have consistent `hl7_` prefix and match DoD: `hl7_messages_total`, `hl7_ack_latency_ms`, `hl7_active_connections`

### Definition of Done Verification

| DoD Item | Task | Status |
|---|---|---|
| asyncio-based MLLP listener using `asyncio.start_server` | TASK-003 | ☐ |
| MLLP framing: VT (0x0B) + FS (0x1C) + CR (0x0D) parsing | TASK-001 | ☐ |
| ACK (MSH + MSA with `AA`) within 200ms | TASK-002, TASK-003 | ☐ |
| NACK (MSH + MSA with `AE` + ERR) on parse failure | TASK-002, TASK-003 | ☐ |
| Connection pool: max 50 concurrent via semaphore | TASK-003 | ☐ |
| TCP keep-alive enabled on all accepted connections | TASK-004 | ☐ |
| Prometheus metrics: `hl7_messages_total`, `hl7_ack_latency_ms`, `hl7_active_connections` | TASK-004 | ☐ |
| `GET /health` and `GET /ready` as asyncio HTTP server | TASK-004 | ☐ |
| Unit tests for MLLP frame parsing and ACK/NACK generation | TASK-005 | ☐ |
| Code reviewed and approved | TASK-006 | ☐ |

---

## Files Delivered

| File | Task |
|---|---|
| `hl7-listener/app/mllp/framing.py` | TASK-001 |
| `hl7-listener/app/mllp/ack_builder.py` | TASK-002 |
| `hl7-listener/app/mllp/server.py` | TASK-003 |
| `hl7-listener/app/main.py` | TASK-003 |
| `hl7-listener/app/metrics.py` | TASK-004 |
| `hl7-listener/app/health.py` | TASK-004 |
| `hl7-listener/Dockerfile` | TASK-004 |
| `hl7-listener/requirements.txt` | TASK-001 |
| `hl7-listener/pytest.ini` | TASK-005 |
| `hl7-listener/tests/unit/mllp/test_framing.py` | TASK-005 |
| `hl7-listener/tests/unit/mllp/test_ack_builder.py` | TASK-005 |

---

## Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Author (Backend Engineer) | | | |
| Peer Reviewer (Backend Engineer) | | | |
| Security Reviewer (Security Engineer) | | | |
