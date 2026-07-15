---
id: TASK-007
title: "Code Review & DoD Sign-off — US-059 JWT Blocklist & Session Timeout"
user_story: US-059
epic: EP-011
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-059/TASK-001, US-059/TASK-002, US-059/TASK-003, US-059/TASK-004, US-059/TASK-005, US-059/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-059 JWT Blocklist & Session Timeout

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-059. It verifies that all implementation tasks (TASK-001 through TASK-006) are complete, all Definition of Done checklist items are met, and both a peer code review and a Security Engineer sign-off have been completed.

The Security Engineer review is required by the US-059 DoD: *"Code reviewed and Security Engineer reviewed"*. This story touches the core authentication middleware (security-critical path), making the Security Engineer review mandatory, not optional.

---

## Pre-Review Validation Sequence

Run the full validation before requesting review:

```bash
cd backend

# 1. Install dependencies (including fakeredis dev dep)
pip install -r requirements.txt -r requirements-dev.txt

# 2. Run the full US-059 unit test suite with coverage
pytest tests/unit/core/auth/test_jwt_blocklist.py \
       tests/unit/api/v1/auth/test_logout.py \
       tests/unit/api/v1/admin/test_deprovision.py \
       -v --tb=short \
       --cov=app/core/auth/jwt_blocklist \
       --cov=app/core/auth/jwt \
       --cov=app/api/v1/auth \
       --cov=app/api/v1/admin/users \
       --cov-report=term-missing \
       --cov-fail-under=80

# 3. Run full unit test suite — no regressions from US-056, US-057, US-058
pytest tests/unit/ -q --tb=short

# 4. Confirm jti claim present in issued JWTs
python -c "
import os
os.environ.setdefault('JWT_SIGNING_KEY', 'test-signing-key-32-chars-padding')
from app.core.auth.jwt import issue_app_jwt
# issue_app_jwt is now async — run in event loop
import asyncio
from unittest.mock import AsyncMock
token = asyncio.run(issue_app_jwt(
    {'sub': 'u1', 'groups': ['smarthandoff-nurse'], 'email': 'n@test.com'},
    db=AsyncMock()
))
from jose import jwt as _j
payload = _j.decode(token, os.environ['JWT_SIGNING_KEY'], algorithms=['HS256'])
assert 'jti' in payload, 'jti missing from JWT'
print('jti present:', payload['jti'])
"

# 5. Confirm blocklist check position (after signature validation)
grep -n "is_blocklisted" backend/app/core/auth/jwt.py
# Expected: appears AFTER the jwt.decode() call block

# 6. Confirm deprovisioned_at column in migration
grep -n "deprovisioned_at" backend/alembic/versions/0004_add_user_jti_deprovisioning.py
# Expected: op.add_column call present

# 7. Bandit SAST — no HIGH/CRITICAL in auth and admin modules
bandit \
  backend/app/core/auth/jwt_blocklist.py \
  backend/app/core/auth/jwt.py \
  backend/app/api/v1/auth.py \
  backend/app/api/v1/admin/users.py \
  -ll

# 8. Frontend — TypeScript compilation clean
cd ../frontend
npx ng build --configuration=development 2>&1 | grep "ERROR" | wc -l
# Expected: 0

# 9. Frontend unit tests
npx jest --testPathPattern="idle-timeout|session-expired" --coverage
```

---

## Code Review Checklist

### Security Review (Security Engineer Required)

- [ ] `is_blocklisted()` called AFTER `jwt.decode()` — not before signature validation (US-059 Technical Notes)
- [ ] Blocklist key uses `jwt_blocklist:{jti}` prefix — no namespace collision with other Redis keys
- [ ] Redis client TTL set to `exp - now` — no unbounded key growth
- [ ] Deprovisioning endpoint requires `ADMIN` role — `require_permission("user", "write")` dependency enforced
- [ ] `DELETE /api/v1/admin/users/{id}` returns `503` (not `200`) if Redis blocklist write fails — fail-closed
- [ ] Logout endpoint returns `200` even if Redis fails (fail-open acceptable for user-initiated logout; Redis failure logged as WARNING)
- [ ] No `jti` or blocklist status revealed in error response bodies — `"Invalid or expired access token"` used uniformly for 401
- [ ] `is_blocklisted()` raises `redis.RedisError` on connection failure — `get_current_user()` converts to `503` (fail-closed, not fail-open)
- [ ] Angular JWT stored only in `AuthService` private field — not in `localStorage`, `sessionStorage`, or cookies (XSS protection; verifiable via browser devtools)
- [ ] `IdleTimeoutService` timer only runs when authenticated — no false-positive logouts on the login page
- [ ] OTP/authentication rate limiting unaffected (no changes to `POST /api/v1/auth/token`)

### Functional Review (Peer Engineer)

- [ ] `add_to_blocklist()` with already-expired token (TTL ≤ 0) skips write and logs debug — no Redis write for useless key
- [ ] Legacy tokens (missing `jti`) are logged as WARNING and allowed through — no hard lockout during deployment
- [ ] Angular `IdleTimeoutService.start()` calls `stop()` first to prevent duplicate subscriptions on re-login
- [ ] `SessionExpiredDialogComponent` has `disableClose: true` — user cannot dismiss by clicking backdrop
- [ ] `SessionExpiredDialogComponent` auto-dismisses after 5 seconds AND redirects — no stuck modal
- [ ] `app_user.current_jti` is updated on every login — not just first login
- [ ] Migration `0004` has a `downgrade()` function — rollback path exists

### Definition of Done Checklist

- [ ] JWT blocklist: Redis SADD `jwt_blocklist:{jti}` on logout/deprovision; TTL = remaining JWT lifetime
- [ ] FastAPI JWT middleware: `if redis.sismember("jwt_blocklist", jti): raise HTTPException(401)`
- [ ] `DELETE /api/v1/admin/users/{id}` deprovisioning endpoint: adds JWT to blocklist + sets `app_user.deprovisioned_at`
- [ ] `POST /api/v1/auth/logout` endpoint: blocklist current JWT + 200 OK
- [ ] Angular `IdleTimeoutService`: RxJS timer resets on any mousemove/keypress/scroll; fires logout at 30 minutes
- [ ] "Session expired" modal: `MatDialog` with auto-dismiss and redirect to login
- [ ] Unit tests: blocklist lookup, deprovisioning flow, idle timeout event
- [ ] Code reviewed and Security Engineer reviewed

---

## Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Peer Code Review | | | |
| Security Engineer | | | |
| Story Owner | | | |
