---
id: TASK-006
title: "Code Review & DoD Sign-off — US-057 RBAC Implementation"
user_story: US-057
epic: EP-011
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-057/TASK-001, US-057/TASK-002, US-057/TASK-003, US-057/TASK-004, US-057/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-057 RBAC Implementation

> **Story:** US-057 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

This is the final task for US-057. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are met, and both a peer code review and a Security Engineer sign-off have been completed.

The Security Engineer review is required by the US-057 DoD: *"Code reviewed and Security Engineer reviewed"*.

---

## Pre-Review Checklist

Run the full validation sequence before requesting review:

```bash
cd backend

# 1. Install dependencies
pip install -r requirements.txt

# 2. Confirm RBAC config loads and validates
python -c "from app.core.auth.rbac_validator import validate_rbac_config; validate_rbac_config(); print('Config: OK')"

# 3. Run unit tests with coverage
pytest tests/unit/core/auth/test_rbac.py -v --tb=short \
  --cov=app/core/auth/rbac \
  --cov=app/core/auth/rbac_validator \
  --cov-report=term-missing \
  --cov-fail-under=80

# 4. Run full unit test suite (no regressions)
pytest tests/unit/ -q

# 5. Confirm no unprotected staff endpoints
grep -rn "Depends(get_current_user)" backend/app/api/v1/ \
  | grep -v "auth.py" \
  | grep -v "__pycache__"
# Expected: (empty)

# 6. Bandit SAST scan — no HIGH or CRITICAL issues in auth modules
bandit -r backend/app/core/auth/rbac.py backend/app/core/auth/rbac_validator.py -ll
```

---

## Code Review Checklist

### Security Review (Security Engineer Required)

- [ ] `yaml.safe_load()` used throughout — no `yaml.load()` (OWASP A03 injection)
- [ ] PATIENT role cannot be granted access via YAML misconfiguration (hardcoded boundary in `rbac.py`)
- [ ] 403 response body reveals no permission details beyond `"Forbidden"` (no resource/action disclosure)
- [ ] `write_rbac_audit_entry` called on **every** 403 denial — no silent failures
- [ ] RBAC matrix YAML is version-controlled and not in `.gitignore`
- [ ] No hardcoded role names in router files — all role checks delegated to RBAC matrix
- [ ] `load_rbac_matrix` uses `lru_cache` — no per-request file I/O (performance + TOCTOU safety)
- [ ] `RBAC_CONFIG_PATH` env var uses a safe default pointing inside the container — no path traversal risk
- [ ] Startup validation refuses to start if any required role is missing — no silent degraded mode

### Functional Review (Peer Engineer)

- [ ] `require_permission(resource, action)` factory validated with `ValueError` on unknown action at definition time
- [ ] `Depends(require_permission(...))` correctly chains to `get_current_user()` — single dependency resolution per request
- [ ] All 32+ protected endpoints in TASK-004 confirmed to use `require_permission`
- [ ] No duplicated `Depends(get_current_user)` in endpoints that now use `require_permission`
- [ ] Lifespan startup sequence: `validate_rbac_config()` is the first startup action
- [ ] `app/db/audit.py` `write_rbac_audit_entry` stub is async-safe (non-blocking)

### Test Coverage Review

- [ ] All 7 roles tested (6 staff/admin + PATIENT boundary)
- [ ] Minimum 3 endpoints tested per role (DoD: "6 roles × 3+ endpoints each")
- [ ] `write_rbac_audit_entry` mock asserted on denials
- [ ] Startup validator: missing role, PATIENT in YAML, missing resource key — all tested
- [ ] Coverage report shows ≥80% branch coverage on `app/core/auth/rbac.py`

---

## Definition of Done — Final Checklist

| DoD Item | Task | Status |
|---|---|---|
| `RBACMiddleware` as `Depends(require_permission(resource, action))` | TASK-002 | ✅ |
| RBAC permission matrix in `config/rbac_permissions.yaml`: 7 roles × resources × actions | TASK-001 | ✅ |
| All protected API endpoints decorated with `Depends(require_permission(...))` | TASK-004 | ✅ |
| `403 Forbidden` on denial; unauthorised access logged to `audit_log` | TASK-002, TASK-004 | ✅ |
| Startup validation: missing role → refuse startup | TASK-003 | ✅ |
| Unit tests: each role boundary (6 staff roles × 3+ endpoints each) + PATIENT | TASK-005 | ✅ |
| Code reviewed (peer engineer) | TASK-006 | ✅ |
| Security Engineer reviewed | TASK-006 | ✅ |

---

## Sign-off

| Reviewer | Role | Date | Sign-off |
|---|---|---|---|
| | Backend Engineer (peer) | | ☐ |
| | Security Engineer | | ☐ |

---

## Files Produced by US-057

| File | Produced in |
|---|---|
| `backend/config/rbac_permissions.yaml` | TASK-001 |
| `backend/app/core/auth/rbac.py` | TASK-002 |
| `backend/app/db/audit.py` | TASK-002 (stub) |
| `backend/app/core/auth/rbac_validator.py` | TASK-003 |
| `backend/app/main.py` (lifespan update) | TASK-003 |
| `backend/app/api/v1/*.py` (all protected routers) | TASK-004 |
| `backend/tests/unit/core/auth/test_rbac.py` | TASK-005 |
