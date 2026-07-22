---
id: TASK-001
title: "Create `config/rbac_permissions.yaml` — 7-Role RBAC Permission Matrix"
user_story: US-057
epic: EP-011
sprint: 1
layer: Backend / Config
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-056/TASK-004]
---

# TASK-001: Create `config/rbac_permissions.yaml` — 7-Role RBAC Permission Matrix

> **Story:** US-057 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend / Config | **Est:** 1 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-057 requires a YAML-based RBAC permission matrix as the single source of truth for all role-resource-action permissions. The file is loaded by `app/core/auth/rbac.py` (TASK-002) and validated at application startup (TASK-003).

Seven clinical roles are defined in AC Scenario 3: `PHYSICIAN`, `NURSE`, `PHARMACIST`, `BED_MANAGER`, `CARE_MANAGER`, `ADMIN`, `PATIENT`. Per the Technical Notes, the `PATIENT` role has an **immutable hardcoded security boundary** in code — it is **not** present in this YAML file (see TASK-002). The YAML therefore contains exactly **6 staff/admin roles**.

Resources and actions are derived from the API router inventory in design.md §3.3 and the RBAC permission matrix in design.md §8.3:

| Resource | Maps to API endpoints |
|---|---|
| `patient` | `GET/PATCH /api/v1/patients`, `GET /api/v1/patients/{id}` |
| `encounter` | `GET/POST/PATCH /api/v1/encounters` |
| `document` | `GET/POST/PATCH /api/v1/documents` |
| `medication` | `GET/POST/PATCH /api/v1/medications` |
| `alert` | `GET/PATCH /api/v1/alerts` |
| `bed` | `GET/POST/PATCH /api/v1/beds` |
| `analytics` | `GET /api/v1/analytics` |
| `audit_log` | `GET /api/v1/admin/audit` |
| `user` | `GET/POST/PATCH /api/v1/admin/users` |
| `agent_task` | `GET /api/v1/tasks` |

---

## Acceptance Criteria Addressed

| US-057 AC | Requirement |
|---|---|
| **Scenario 3** | RBAC matrix loaded from `config/rbac_permissions.yaml`; all 7 roles defined; missing role → startup error |
| **DoD** | `config/rbac_permissions.yaml`: 7 roles × resources × actions (READ/WRITE/APPROVE/RESOLVE) |

---

## Implementation Steps

### 1. Create `backend/config/rbac_permissions.yaml`

Create the file at `backend/config/rbac_permissions.yaml` with the content below. The `patient:` key under each role is intentionally listed first to mirror the HIPAA minimum-necessary ordering (most sensitive resource stated explicitly).

> **Security note:** Actions listed are the complete set a role is *permitted* to perform. Any action not listed is implicitly **denied**. Empty lists `[]` are explicit deny — do not omit the resource key, because the startup validator (TASK-003) confirms all expected resource keys are present for each role.

```yaml
# SmartHandoff RBAC Permission Matrix
#
# Source of truth for role-based access control (SEC-002, US-057).
# Loaded at application startup; changes require re-deploy.
#
# PATIENT role is NOT defined here — it has a hardcoded security boundary
# in app/core/auth/rbac.py. Any attempt to add PATIENT here is silently
# ignored by the loader and flagged in startup validation logs.
#
# Permitted actions per resource:
#   list    — collection endpoint (GET /resource)
#   read    — single-item endpoint (GET /resource/{id})
#   write   — create or update (POST, PATCH, PUT)
#   approve — approve a document (PATCH /documents/{id}/approve)
#   resolve — resolve an alert (PATCH /alerts/{id}/resolve)
#
# Design ref: design.md §8.3 RBAC Permission Matrix

roles:

  ADMIN:
    patient:    [list, read, write]
    encounter:  [list, read, write]
    document:   [list, read, write, approve]
    medication: [list, read, write]
    alert:      [list, read, resolve]
    bed:        [list, read, write]
    analytics:  [list, read]
    audit_log:  [list, read]
    user:       [list, read, write]
    agent_task: [list, read]

  PHYSICIAN:
    patient:    [list, read]
    encounter:  [list, read]
    document:   [list, read, approve]
    medication: [list, read]
    alert:      [list, read]
    bed:        []
    analytics:  []
    audit_log:  []
    user:       []
    agent_task: [list, read]

  NURSE:
    patient:    [list, read]
    encounter:  [list, read]
    document:   [list, read]
    medication: [list, read]
    alert:      [list, read]
    bed:        []
    analytics:  []
    audit_log:  []
    user:       []
    agent_task: [list, read]

  PHARMACIST:
    patient:    [read]
    encounter:  [read]
    document:   []
    medication: [list, read, write]
    alert:      [list, read, resolve]
    bed:        []
    analytics:  []
    audit_log:  []
    user:       []
    agent_task: []

  BED_MANAGER:
    patient:    []
    encounter:  [list, read]
    document:   []
    medication: []
    alert:      [list, read]
    bed:        [list, read, write]
    analytics:  [list, read]
    audit_log:  []
    user:       []
    agent_task: []

  CARE_MANAGER:
    patient:    [list, read]
    encounter:  [list, read]
    document:   [list, read]
    medication: [list, read]
    alert:      [list, read]
    bed:        []
    analytics:  [list, read]
    audit_log:  []
    user:       []
    agent_task: [list, read]
```

### 2. Create `backend/config/` `__init__` placeholder (if absent)

The `config/` directory is a plain filesystem directory, not a Python package. Verify it does not already exist:

```bash
ls backend/config/ 2>/dev/null || mkdir -p backend/config
```

### 3. Add YAML to `.gitignore` exclusion review

The RBAC matrix is **not a secret** — it must be committed to version control so that CI/CD can validate it and team members can review permission changes in pull requests. Confirm that `backend/config/rbac_permissions.yaml` is **not** listed in `.gitignore`.

---

## Validation

```bash
# Confirm valid YAML syntax
python -c "import yaml; d = yaml.safe_load(open('backend/config/rbac_permissions.yaml')); print(list(d['roles'].keys()))"
# Expected output: ['ADMIN', 'PHYSICIAN', 'NURSE', 'PHARMACIST', 'BED_MANAGER', 'CARE_MANAGER']

# Confirm 6 roles × 10 resources each
python -c "
import yaml
data = yaml.safe_load(open('backend/config/rbac_permissions.yaml'))
for role, perms in data['roles'].items():
    assert len(perms) == 10, f'{role} has {len(perms)} resources, expected 10'
    print(f'{role}: OK ({len(perms)} resources)')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/config/rbac_permissions.yaml` | Create with 6-role permission matrix |

---

## Definition of Done Checklist

- [ ] `backend/config/rbac_permissions.yaml` exists and parses as valid YAML
- [ ] Exactly 6 staff/admin roles defined (PATIENT absent from YAML)
- [ ] All 10 resource keys present under every role (including empty-list `[]` entries)
- [ ] Actions restricted to: `list`, `read`, `write`, `approve`, `resolve`
- [ ] File committed to version control; not in `.gitignore`
- [ ] YAML syntax validated via `python -c` command above
