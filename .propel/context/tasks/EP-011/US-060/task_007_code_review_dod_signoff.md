---
id: TASK-007
title: "Code Review & DoD Sign-off — US-060 SCIM 2.0 Provisioning"
user_story: US-060
epic: EP-011
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-060/TASK-001, US-060/TASK-002, US-060/TASK-003, US-060/TASK-004, US-060/TASK-005, US-060/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-060 SCIM 2.0 Provisioning

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-060. It verifies that all implementation tasks (TASK-001 through TASK-006) are complete, all Definition of Done checklist items are met, and both a peer code review and a Security Engineer sign-off have been completed.

US-060 DoD states: *"Code reviewed and Security Engineer reviewed"*. This story exposes a new public SCIM endpoint backed by a separate authentication mechanism — the Security Engineer review is mandatory, not optional, to validate:
- SCIM bearer token auth cannot be bypassed
- `hmac.compare_digest` is correctly applied (timing-safe comparison)
- `deprovision_user()` is called — not bypassed — in the SCIM DELETE path
- No PHI appears in structured logs

---

## Pre-Review Validation Sequence

```bash
cd backend

# 1. Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# 2. Run the full US-060 test suite with coverage
pytest tests/unit/api/v1/admin/scim/test_scim_endpoints.py \
       -v --tb=short \
       --cov=app/api/v1/admin/scim \
       --cov=app/services/deprovision_service \
       --cov-report=term-missing \
       --cov-fail-under=80

# 3. Run full unit suite — no regressions from US-056 through US-059
pytest tests/unit/ -q --tb=short

# 4. Confirm all SCIM routes are registered
python -c "
from app.main import app
scim_routes = [(r.path, sorted(r.methods)) for r in app.routes if 'scim' in r.path]
print('SCIM routes:', scim_routes)
required_methods = {'POST', 'GET', 'PATCH', 'PUT', 'DELETE'}
all_methods = {m for _, methods in scim_routes for m in methods}
missing = required_methods - all_methods
assert not missing, f'Missing SCIM methods: {missing}'
print('All required SCIM methods present')
"

# 5. Confirm hmac.compare_digest is used in scim_auth (not == comparison)
grep -n "compare_digest" backend/app/api/v1/admin/scim/scim_auth.py
# Expected: at least one match on the token comparison line

# 6. Confirm SCIM_CLIENT_SECRET is not hardcoded anywhere
grep -rn "scim.*secret\|bearer.*token" backend/app/ --include="*.py" | grep -v "test_" | grep -v "config.py"
# Expected: no lines containing literal token values

# 7. Confirm scim_id column in migration
grep -n "scim_id" backend/alembic/versions/0005_add_scim_id_to_app_user.py
# Expected: op.add_column call for scim_id present

# 8. Confirm SCIM role mapping config is in place
python -c "
from app.api.v1.admin.scim.schemas import ScimRoleMapper
mapper = ScimRoleMapper.load()
for dept in ['Nursing', 'Pharmacy', 'Medicine', 'BedManagement', 'Administration']:
    role = mapper.map(dept)
    print(f'  {dept} → {role}')
print('All canonical departments mapped OK')
"

# 9. Confirm deprovision_service is NOT duplicated — SCIM DELETE and manual DELETE
#    both call the same function
grep -rn "deprovision_user" backend/app/api/ --include="*.py"
# Expected: both scim/router.py and admin/users.py import from services/deprovision_service

# 10. Confirm no PHI in SCIM log statements
grep -n "logger\." backend/app/api/v1/admin/scim/router.py
# Review: no 'email', 'display_name', 'name' in log extra fields
```

---

## Definition of Done Checklist

| DoD Item | Verification |
|---|---|
| `POST`, `GET`, `PATCH`, `PUT`, `DELETE` `/api/v1/admin/scim/Users` | Step 4 above: all 5 methods present |
| SCIM bearer token authentication | Step 5+6: `compare_digest` used; no hardcoded secrets |
| `config/scim_role_mapping.yaml` | Step 8: all canonical departments map correctly |
| SCIM DELETE calls `deprovisioning_service.deprovision_user()` | Step 9: single shared implementation |
| SCIM 2.0 response schemas (RFC 7643) | Schemas in `scim/schemas.py`; `ScimUserResponse`, `ScimListResponse` present |
| Unit tests: create, update, delete, auth failure | Step 2: ≥80% coverage, all 4 AC scenarios covered |
| Code reviewed | Peer reviewer sign-off on PR |
| Security Engineer reviewed | Security Engineer sign-off required before merge |

---

## Security Review Focus Areas

The Security Engineer review should specifically validate:

1. **SCIM token comparison** — `hmac.compare_digest` used, not `==` (prevents timing attack)
2. **Token storage** — `SCIM_CLIENT_SECRET` loaded from Secret Manager env var; not logged
3. **Deprovision path** — `DELETE` and `PATCH active=False` both call `deprovision_user()` with no bypass path
4. **PHI in logs** — `logger.info/warning` calls in `scim_auth.py` and `router.py` contain only `user_id` (UUID), never email, name, or department
5. **404 vs 403** — returning `404` (not `403`) for missing users prevents user enumeration via SCIM (per OWASP API Security Top 10 — API3:2023)
6. **Input validation** — `userName` validated as non-empty; department validated against allowlist (YAML mapping acts as allowlist)

---

## Files Produced by US-060 (Full List)

| File | Task |
|---|---|
| `config/scim_role_mapping.yaml` | TASK-001 |
| `backend/app/api/v1/admin/scim/__init__.py` | TASK-001 |
| `backend/app/api/v1/admin/scim/schemas.py` | TASK-001 |
| `backend/app/api/v1/admin/scim/scim_auth.py` | TASK-002 |
| `backend/alembic/versions/0005_add_scim_id_to_app_user.py` | TASK-003 |
| `backend/app/api/v1/admin/scim/router.py` | TASK-003, TASK-004, TASK-005 |
| `backend/app/services/deprovision_service.py` | TASK-005 |
| `backend/tests/unit/api/v1/admin/scim/__init__.py` | TASK-006 |
| `backend/tests/unit/api/v1/admin/scim/test_scim_endpoints.py` | TASK-006 |
| `backend/app/core/config.py` | TASK-002 (add `SCIM_CLIENT_SECRET`) |
| `backend/app/api/v1/router.py` | TASK-003 (register SCIM router) |
| `backend/app/api/v1/admin/users.py` | TASK-005 (delegate to `deprovision_service`) |
| `backend/requirements.txt` | TASK-001 (add `pyyaml` if absent) |
