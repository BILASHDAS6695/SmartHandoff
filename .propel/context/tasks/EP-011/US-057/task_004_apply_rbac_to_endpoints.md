---
id: TASK-004
title: "Apply `require_permission` to All Protected API Endpoints + 403 Audit Logging"
user_story: US-057
epic: EP-011
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-057/TASK-002, US-057/TASK-003]
---

# TASK-004: Apply `require_permission` to All Protected API Endpoints + 403 Audit Logging

> **Story:** US-057 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

With the RBAC matrix and dependency implemented (TASK-001–003), this task wires `require_permission(resource, action)` onto every protected API endpoint. The design.md §3.3 middleware stack defines RBAC at position 5 — after JWT validation — so `require_permission` wraps `get_current_user()` via `Depends()` chaining.

Each endpoint currently uses `Depends(get_current_user)` for authentication only. This task replaces those dependencies with `Depends(require_permission(resource, action))` which internally calls `get_current_user()` — no double dependency injection.

The `write_rbac_audit_entry` stub from TASK-002 already handles denial logging. This task also wires the **grant** audit log for successful accesses to complete the HIPAA audit trail requirement (BR-023).

### Endpoint-to-Permission Mapping

| Router | Method + Path | Resource | Action |
|--------|--------------|----------|--------|
| patients | `GET /patients` | `patient` | `list` |
| patients | `GET /patients/{id}` | `patient` | `read` |
| patients | `PATCH /patients/{id}` | `patient` | `write` |
| encounters | `GET /encounters` | `encounter` | `list` |
| encounters | `GET /encounters/{id}` | `encounter` | `read` |
| encounters | `POST /encounters` | `encounter` | `write` |
| encounters | `PATCH /encounters/{id}` | `encounter` | `write` |
| documents | `GET /documents` | `document` | `list` |
| documents | `GET /documents/{id}` | `document` | `read` |
| documents | `POST /documents` | `document` | `write` |
| documents | `PATCH /documents/{id}/approve` | `document` | `approve` |
| medications | `GET /medications` | `medication` | `list` |
| medications | `GET /medications/{id}` | `medication` | `read` |
| medications | `POST /medications` | `medication` | `write` |
| medications | `PATCH /medications/{id}` | `medication` | `write` |
| alerts | `GET /alerts` | `alert` | `list` |
| alerts | `GET /alerts/{id}` | `alert` | `read` |
| alerts | `PATCH /alerts/{id}/resolve` | `alert` | `resolve` |
| beds | `GET /beds` | `bed` | `list` |
| beds | `GET /beds/{id}` | `bed` | `read` |
| beds | `POST /beds` | `bed` | `write` |
| beds | `PATCH /beds/{id}` | `bed` | `write` |
| analytics | `GET /analytics` | `analytics` | `read` |
| analytics | `GET /analytics/{report}` | `analytics` | `read` |
| admin/audit | `GET /admin/audit` | `audit_log` | `list` |
| admin/audit | `GET /admin/audit/{id}` | `audit_log` | `read` |
| admin/users | `GET /admin/users` | `user` | `list` |
| admin/users | `GET /admin/users/{id}` | `user` | `read` |
| admin/users | `POST /admin/users` | `user` | `write` |
| admin/users | `PATCH /admin/users/{id}` | `user` | `write` |
| tasks | `GET /tasks` | `agent_task` | `list` |
| tasks | `GET /tasks/{id}` | `agent_task` | `read` |

---

## Acceptance Criteria Addressed

| US-057 AC | Requirement |
|---|---|
| **Scenario 1** | `PATCH /alerts/{id}/resolve` decorated with `require_permission("alert", "resolve")` |
| **Scenario 2** | Pharmacist resolves alert → 2xx; audit log records grant |
| **DoD** | All protected API endpoints decorated with `Depends(require_permission("resource", "action"))` |
| **DoD** | `403 Forbidden` on denial; unauthorised access attempts logged to `audit_log` |

---

## Implementation Steps

### 1. Update `write_rbac_audit_entry` to Support Grant Logging

Extend the `write_rbac_audit_entry` stub in `backend/app/db/audit.py` to accept a `granted=True` call. The existing stub already accepts `granted: bool` — verify the call sites in the routers can pass `granted=True` for successful access.

> No code change needed in `audit.py` if TASK-002 implemented `granted: bool` as shown. Confirm the stub signature and proceed.

### 2. Update Each Router File

For each router listed in the endpoint mapping above, replace `Depends(get_current_user)` with `Depends(require_permission(resource, action))`.

**Pattern to apply uniformly:**

```python
# BEFORE (authentication only):
from app.core.auth.jwt import TokenClaims, get_current_user

@router.get("/patients")
async def list_patients(
    current_user: TokenClaims = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ...

# AFTER (authentication + RBAC):
from app.core.auth.rbac import require_permission
from app.core.auth.jwt import TokenClaims

@router.get("/patients")
async def list_patients(
    current_user: TokenClaims = Depends(require_permission("patient", "list")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

> **Note:** `require_permission` returns a dependency that itself depends on `get_current_user`, so `current_user` in the function signature still resolves to the `TokenClaims` object. The `Depends()` chain is: request → JWT validation → RBAC check → handler.

### 3. Apply to `backend/app/api/v1/patients.py`

```python
from app.core.auth.rbac import require_permission
from app.core.auth.jwt import TokenClaims

@router.get("/patients", response_model=list[PatientSummary])
async def list_patients(
    current_user: TokenClaims = Depends(require_permission("patient", "list")),
    db: AsyncSession = Depends(get_db),
):
    ...

@router.get("/patients/{patient_id}", response_model=PatientDetail)
async def get_patient(
    patient_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permission("patient", "read")),
    db: AsyncSession = Depends(get_db),
):
    ...

@router.patch("/patients/{patient_id}", response_model=PatientDetail)
async def update_patient(
    patient_id: uuid.UUID,
    body: PatientUpdate,
    current_user: TokenClaims = Depends(require_permission("patient", "write")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

### 4. Apply to `backend/app/api/v1/documents.py`

The `approve` action is the key business-critical permission — only PHYSICIANs can approve discharge documents (design.md §8.3):

```python
@router.patch("/documents/{document_id}/approve", response_model=DocumentDetail)
async def approve_document(
    document_id: uuid.UUID,
    current_user: TokenClaims = Depends(require_permission("document", "approve")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

### 5. Apply to `backend/app/api/v1/alerts.py`

The `resolve` action is the boundary tested in US-057 AC Scenario 1 (NURSE denied) and Scenario 2 (PHARMACIST granted):

```python
@router.patch("/alerts/{alert_id}/resolve", response_model=AlertDetail)
async def resolve_alert(
    alert_id: uuid.UUID,
    body: AlertResolveRequest,
    current_user: TokenClaims = Depends(require_permission("alert", "resolve")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

### 6. Apply to `backend/app/api/v1/beds.py`

```python
@router.get("/beds", response_model=list[BedSummary])
async def list_beds(
    current_user: TokenClaims = Depends(require_permission("bed", "list")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

### 7. Apply to Remaining Routers

Apply the same pattern to all remaining routers listed in the endpoint mapping table:
- `backend/app/api/v1/encounters.py`
- `backend/app/api/v1/medications.py`
- `backend/app/api/v1/analytics.py`
- `backend/app/api/v1/tasks.py`
- `backend/app/api/v1/admin/audit.py`
- `backend/app/api/v1/admin/users.py`

### 8. Verify No Unprotected Staff Endpoints Remain

After updating all routers, run a grep to confirm no endpoint uses `get_current_user` directly in a staff-facing router (the auth router `/auth/*` is exempt as it issues tokens, not consumes them):

```bash
grep -rn "Depends(get_current_user)" backend/app/api/v1/ \
  | grep -v "auth.py" \
  | grep -v "__pycache__"
```

**Expected output:** no matches. Any match indicates a router that was missed.

---

## Validation

```bash
cd backend

# Run existing test suite to confirm no regressions
pytest tests/unit/ -q

# Confirm the grep above returns no unprotected endpoints
grep -rn "Depends(get_current_user)" backend/app/api/v1/ \
  | grep -v "auth.py" \
  | grep -v "__pycache__"
# Expected: (empty)
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/api/v1/patients.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/encounters.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/documents.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/medications.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/alerts.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/beds.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/analytics.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/tasks.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/admin/audit.py` | Replace `get_current_user` with `require_permission(...)` |
| `backend/app/api/v1/admin/users.py` | Replace `get_current_user` with `require_permission(...)` |

---

## Definition of Done Checklist

- [ ] All 32+ protected endpoints use `Depends(require_permission(resource, action))`
- [ ] No staff-facing endpoint uses bare `Depends(get_current_user)` (confirmed by grep)
- [ ] `PATCH /alerts/{id}/resolve` uses `require_permission("alert", "resolve")`
- [ ] `PATCH /documents/{id}/approve` uses `require_permission("document", "approve")`
- [ ] Audit log called for denials (via `write_rbac_audit_entry(granted=False)`)
- [ ] Existing unit tests pass with no regressions (`pytest tests/unit/ -q`)
