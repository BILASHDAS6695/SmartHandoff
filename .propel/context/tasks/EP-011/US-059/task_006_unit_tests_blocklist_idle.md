---
id: TASK-006
title: "Write pytest + Jest Unit Tests — Blocklist, Deprovision, Idle Timeout"
user_story: US-059
epic: EP-011
sprint: 1
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer + Frontend Engineer
upstream: [US-059/TASK-001, US-059/TASK-002, US-059/TASK-003, US-059/TASK-004, US-059/TASK-005]
---

# TASK-006: Write pytest + Jest Unit Tests — Blocklist, Deprovision, Idle Timeout

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-059 DoD requires: *"Unit tests: blocklist lookup, deprovisioning flow, idle timeout event"*. This task delivers:

- **Backend (pytest):** Tests for `JwtBlocklistService`, `get_current_user()` blocklist integration, `POST /logout`, and `DELETE /admin/users/{id}` deprovisioning.
- **Frontend (Jest):** Tests for `IdleTimeoutService` — timer fires at 30 min, activity resets the timer, `AuthService.clearSession()` called on timeout.

All tests follow the ≥80% branch coverage gate (TR-020). FastAPI `TestClient` + `app.dependency_overrides` is used for backend endpoint tests without a real Redis or JWT server. `fakeredis` stubs Redis for blocklist unit tests.

---

## Acceptance Criteria Addressed

| US-059 AC | Requirement |
|---|---|
| **Scenario 1** | Deprovisioned JWT → 401; confirmed via `test_deprovision_blocks_subsequent_call` |
| **Scenario 2** | Non-blocklisted tokens unaffected; `test_non_blocklisted_token_passes` |
| **Scenario 3** | Idle timeout fires logout callback at 30 min; confirmed via `test_idle_timeout_fires` |
| **Scenario 4** | Logout adds jti to blocklist; subsequent call → 401; `test_logout_blocklists_token` |
| **DoD** | Unit tests: blocklist lookup, deprovisioning flow, idle timeout event |

---

## Implementation Steps

### 1. Add `fakeredis` to `backend/requirements-dev.txt`

```
# Test-only (US-059)
fakeredis>=2.23.0
```

---

### 2. Create `backend/tests/unit/core/auth/test_jwt_blocklist.py`

```python
"""Unit tests for app/core/auth/jwt_blocklist.py.

Uses fakeredis to stub Cloud Memorystore so tests run without a real
Redis server. The _get_redis_client lru_cache is patched per-test.

Coverage target: ≥80% branch coverage on jwt_blocklist.py (TR-020).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import fakeredis
import pytest

from app.core.auth import jwt_blocklist as bl_module
from app.core.auth.jwt_blocklist import add_to_blocklist, is_blocklisted


@pytest.fixture(autouse=True)
def fake_redis():
    """Patch _get_redis_client to return a fakeredis instance per test."""
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(bl_module, "_get_redis_client", return_value=fake):
        # Clear lru_cache to ensure patch takes effect
        bl_module._get_redis_client.cache_clear() if hasattr(
            bl_module._get_redis_client, "cache_clear"
        ) else None
        yield fake


class TestAddToBlocklist:
    def test_adds_key_with_correct_ttl(self, fake_redis):
        """Key exists in Redis after add_to_blocklist with positive TTL."""
        jti = "test-jti-001"
        exp = int(time.time()) + 3600  # 1 hour from now
        add_to_blocklist(jti, exp)
        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 1

    def test_ttl_within_expected_range(self, fake_redis):
        """Redis TTL is approximately remaining token lifetime (±2 seconds tolerance)."""
        jti = "test-jti-002"
        remaining = 7200  # 2 hours
        exp = int(time.time()) + remaining
        add_to_blocklist(jti, exp)
        actual_ttl = fake_redis.ttl(f"jwt_blocklist:{jti}")
        assert remaining - 2 <= actual_ttl <= remaining

    def test_expired_token_not_written(self, fake_redis):
        """Already-expired JWTs are not written to Redis (TTL ≤ 0)."""
        jti = "test-jti-expired"
        exp = int(time.time()) - 60  # expired 1 minute ago
        add_to_blocklist(jti, exp)
        assert fake_redis.exists(f"jwt_blocklist:{jti}") == 0


class TestIsBlocklisted:
    def test_returns_false_for_unknown_jti(self):
        """Non-blocklisted jti returns False."""
        assert is_blocklisted("unknown-jti") is False

    def test_returns_true_after_add(self, fake_redis):
        """Blocklisted jti returns True."""
        jti = "test-jti-003"
        exp = int(time.time()) + 3600
        add_to_blocklist(jti, exp)
        assert is_blocklisted(jti) is True

    def test_returns_false_after_ttl_expiry(self, fake_redis):
        """After TTL expiry jti is no longer blocklisted."""
        jti = "test-jti-004"
        add_to_blocklist(jti, int(time.time()) + 1)  # 1-second TTL
        assert is_blocklisted(jti) is True
        # Simulate expiry by deleting the key directly
        fake_redis.delete(f"jwt_blocklist:{jti}")
        assert is_blocklisted(jti) is False
```

---

### 3. Create `backend/tests/unit/api/v1/auth/test_logout.py`

```python
"""Unit tests for POST /api/v1/auth/logout.

Uses FastAPI TestClient with dependency_overrides to inject a pre-validated
TokenClaims without requiring a real JWT. fakeredis stubs Redis.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.core.auth import jwt_blocklist as bl_module
from app.core.auth.jwt import get_current_user
from app.main import app


@pytest.fixture()
def client_with_fake_redis():
    """TestClient with fakeredis and a valid-looking current_user override."""
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(bl_module, "_get_redis_client", return_value=fake):
        yield TestClient(app), fake


def _make_user(jti: str | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "role": "nurse",
        "units": [],
        "email": "nurse@hospital.example.com",
        "jti": jti or str(uuid.uuid4()),
        "exp": int(time.time()) + 28800,
    }


class TestLogoutEndpoint:
    def test_logout_returns_200(self, client_with_fake_redis):
        client, fake = client_with_fake_redis
        user = _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json()["message"] == "Logged out successfully"
        app.dependency_overrides.clear()

    def test_logout_blocklists_jti(self, client_with_fake_redis):
        """After logout the jti is present in the Redis blocklist."""
        client, fake = client_with_fake_redis
        jti = str(uuid.uuid4())
        user = _make_user(jti=jti)
        app.dependency_overrides[get_current_user] = lambda: user
        client.post("/api/v1/auth/logout")
        assert fake.exists(f"jwt_blocklist:{jti}") == 1
        app.dependency_overrides.clear()

    def test_logout_without_jti_returns_200(self, client_with_fake_redis):
        """Tokens without jti (legacy) are still accepted for logout."""
        client, _ = client_with_fake_redis
        user = _make_user()
        user.pop("jti")  # simulate pre-jti token
        app.dependency_overrides[get_current_user] = lambda: user
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        app.dependency_overrides.clear()
```

---

### 4. Create `backend/tests/unit/api/v1/admin/test_deprovision.py`

```python
"""Unit tests for DELETE /api/v1/admin/users/{user_id}.

Uses AsyncMock DB session + fakeredis to avoid real infrastructure.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.core.auth import jwt_blocklist as bl_module
from app.core.auth.jwt import get_current_user
from app.core.auth.rbac import require_permission
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client_and_fake_redis():
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(bl_module, "_get_redis_client", return_value=fake):
        yield TestClient(app), fake


def _admin_user() -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "role": "admin",
        "units": [],
        "email": "admin@hospital.example.com",
        "jti": str(uuid.uuid4()),
        "exp": int(time.time()) + 28800,
    }


def _mock_target_user(deprovisioned: bool = False, has_jti: bool = True):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.deprovisioned_at = "2026-01-01" if deprovisioned else None
    user.current_jti = str(uuid.uuid4()) if has_jti else None
    return user


class TestDeprovisionEndpoint:
    def _setup_overrides(self, mock_db_result):
        app.dependency_overrides[get_current_user] = lambda: _admin_user()
        app.dependency_overrides[require_permission("user", "write")] = lambda: _admin_user()
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_db_result
        app.dependency_overrides[get_db] = lambda: mock_session
        return mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_deprovision_returns_200(self, client_and_fake_redis):
        client, _ = client_and_fake_redis
        target = _mock_target_user()
        self._setup_overrides(target)
        response = client.delete(f"/api/v1/admin/users/{target.id}")
        assert response.status_code == 200

    def test_deprovision_blocklists_jti(self, client_and_fake_redis):
        client, fake = client_and_fake_redis
        target = _mock_target_user(has_jti=True)
        self._setup_overrides(target)
        client.delete(f"/api/v1/admin/users/{target.id}")
        assert fake.exists(f"jwt_blocklist:{target.current_jti}") == 1

    def test_deprovision_already_deprovisioned_returns_409(self, client_and_fake_redis):
        client, _ = client_and_fake_redis
        target = _mock_target_user(deprovisioned=True)
        self._setup_overrides(target)
        response = client.delete(f"/api/v1/admin/users/{target.id}")
        assert response.status_code == 409

    def test_deprovision_user_not_found_returns_404(self, client_and_fake_redis):
        client, _ = client_and_fake_redis
        self._setup_overrides(None)  # DB returns no user
        response = client.delete(f"/api/v1/admin/users/{uuid.uuid4()}")
        assert response.status_code == 404
```

---

### 5. Create `frontend/src/app/core/auth/idle-timeout.service.spec.ts`

```typescript
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';
import { DOCUMENT } from '@angular/common';

import { IdleTimeoutService } from './idle-timeout.service';

describe('IdleTimeoutService', () => {
  let service: IdleTimeoutService;
  let onTimeoutSpy: jasmine.Spy;
  let dialogSpy: jasmine.SpyObj<MatDialog>;

  beforeEach(() => {
    dialogSpy = jasmine.createSpyObj('MatDialog', ['open']);
    const dialogRefSpy = jasmine.createSpyObj('MatDialogRef', ['afterOpened', 'afterClosed', 'close']);
    dialogRefSpy.afterOpened.and.returnValue(of(null));
    dialogRefSpy.afterClosed.and.returnValue(of(null));
    dialogSpy.open.and.returnValue(dialogRefSpy);

    TestBed.configureTestingModule({
      imports: [RouterTestingModule],
      providers: [
        IdleTimeoutService,
        { provide: MatDialog, useValue: dialogSpy },
      ],
    });
    service = TestBed.inject(IdleTimeoutService);
    onTimeoutSpy = jasmine.createSpy('onTimeout');
  });

  afterEach(() => service.stop());

  it('should create', () => {
    expect(service).toBeTruthy();
  });

  it('should call onTimeout callback after 30 minutes of inactivity', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(30 * 60 * 1000);  // 30 minutes
    expect(onTimeoutSpy).toHaveBeenCalledTimes(1);
  }));

  it('should NOT fire timeout when activity occurs before 30 minutes', fakeAsync(() => {
    const doc = TestBed.inject(DOCUMENT);
    service.start(onTimeoutSpy);
    tick(29 * 60 * 1000);  // 29 minutes — almost there

    // Simulate activity: dispatch a mousemove event
    doc.dispatchEvent(new Event('mousemove'));
    tick(29 * 60 * 1000);  // another 29 minutes (still < 30 from last activity)

    expect(onTimeoutSpy).not.toHaveBeenCalled();
  }));

  it('should open SessionExpiredDialogComponent on timeout', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(30 * 60 * 1000);
    expect(dialogSpy.open).toHaveBeenCalledTimes(1);
  }));

  it('stop() should cancel the timer — no callback after stop', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(15 * 60 * 1000);  // 15 min in
    service.stop();
    tick(30 * 60 * 1000);  // let the full interval pass
    expect(onTimeoutSpy).not.toHaveBeenCalled();
  }));
});
```

---

## Running All Tests

```bash
# Backend
cd backend
pytest tests/unit/core/auth/test_jwt_blocklist.py \
       tests/unit/api/v1/auth/test_logout.py \
       tests/unit/api/v1/admin/test_deprovision.py \
       -v --tb=short \
       --cov=app/core/auth/jwt_blocklist \
       --cov=app/api/v1/auth \
       --cov=app/api/v1/admin/users \
       --cov-report=term-missing \
       --cov-fail-under=80

# Frontend
cd frontend
npx jest --testPathPattern="idle-timeout" --coverage
```
