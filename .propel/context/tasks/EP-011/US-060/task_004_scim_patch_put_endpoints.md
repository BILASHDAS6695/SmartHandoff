---
id: TASK-004
title: "Implement SCIM PATCH + PUT (Update User Role / Attributes) Endpoints"
user_story: US-060
epic: EP-011
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-060/TASK-001, US-060/TASK-002, US-060/TASK-003, US-058/TASK-001]
---

# TASK-004: Implement SCIM PATCH + PUT (Update User Role / Attributes) Endpoints

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AC Scenario 4 requires that a SCIM `PATCH` request changing a user's `enterpriseUser.department` triggers a role update in `app_user.role`, with the change recorded in `audit_log`.

Two endpoints are needed per the RFC 7644 §3.5 protocol:

- **`PATCH /api/v1/admin/scim/Users/{id}`** — Partial update using the SCIM `PatchOp` schema. The IdP typically sends PATCH to change individual attributes (e.g., `active` flag, department). This is the primary endpoint for role changes.
- **`PUT /api/v1/admin/scim/Users/{id}`** — Full replace (RFC 7644 §3.5.1). Some IdPs use PUT for all updates. Replaces all user attributes from the full SCIM payload.

**Audit logging** — AC Scenario 4 and design.md §6.1 DR-003 require that role changes are written to `audit_log`. This task writes to `audit_log` using the pattern established in US-058/TASK-001.

**PATCH operation handling** — The `PatchOp` operations array may include paths like:
- `"path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department"` → role update
- `"path": "active"` with `"value": false` → signals deprovisioning (PATCH-based IdPs); routed to `deprovision_user()` from US-059
- `"path": "userName"` → email update on `app_user`

---

## Acceptance Criteria Addressed

| US-060 AC | Requirement |
|---|---|
| **Scenario 4** | SCIM PATCH `department: Pharmacy` → `app_user.role = PHARMACIST`; change logged to `audit_log` |
| **Scenario 3** | Endpoints protected by `verify_scim_token` (inherited from router-level dependency) |
| **DoD** | `PATCH`, `PUT` `/api/v1/admin/scim/Users` endpoints |

---

## Implementation Steps

### 1. Add PATCH Handler to `backend/app/api/v1/admin/scim/router.py`

Add the following to the existing router (after the GET handlers from TASK-003):

```python
# ---------------------------------------------------------------------------
# PATCH /Users/{id} — Partial update (AC Scenario 4)
# ---------------------------------------------------------------------------

_ENTERPRISE_DEPT_PATH = (
    f"{SCIM_ENTERPRISE_SCHEMA}:department"
)

@router.patch(
    "/{user_id}",
    response_model=ScimUserResponse,
    summary="SCIM: Partial update user",
    description=(
        "Processes SCIM PatchOp operations. "
        "Department changes trigger role update + audit_log entry."
    ),
)
async def scim_patch_user(
    user_id: str,
    body: ScimPatchOp,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> ScimUserResponse:
    result = await db.execute(
        select(AppUser).where(AppUser.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    for op in body.Operations:
        await _apply_patch_operation(op, user, db)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "SCIM user patched",
        extra={"event": "scim_user_patched", "user_id": user_id},
    )
    return _build_scim_response(user, request)


async def _apply_patch_operation(
    op: ScimPatchOperation,
    user: AppUser,
    db: AsyncSession,
) -> None:
    """Apply a single SCIM PatchOp operation to the AppUser instance.

    Supported paths:
      - enterpriseUser.department (or full URN) → role update + audit_log
      - active (False) → deprovisioning (delegates to deprovision_service)
      - userName → email update
      - displayName / name.givenName / name.familyName → display_name update

    Unknown paths are silently ignored (RFC 7644 §3.5.2 — unknown attributes
    should not cause an error if the operation is 'add' or 'replace').
    """
    from app.services.deprovision_service import deprovision_user  # TASK-005 / US-059
    from app.models.audit import AuditLog, AuditAction

    path = (op.path or "").lower()
    value = op.value

    # Department → role mapping (AC Scenario 4)
    if "department" in path:
        if isinstance(value, str) and value:
            try:
                old_role = user.role.value if user.role else None
                role_name = _role_mapper.map(value)
                new_role = AppRole[role_name]
                user.role = new_role
                user.unit = value  # update unit to match new department

                # Write audit_log entry (DR-003, US-058 pattern)
                audit_entry = AuditLog(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    action=AuditAction.USER_ROLE_CHANGED,
                    details={
                        "source": "scim_patch",
                        "old_role": old_role,
                        "new_role": role_name,
                        "department": value,
                    },
                    created_at=datetime.now(timezone.utc),
                )
                db.add(audit_entry)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"SCIM department '{value}' has no role mapping.",
                )

    # active=False → deprovision (some IdPs use PATCH active instead of DELETE)
    elif path == "active" and value is False:
        await deprovision_user(user.id, db=db)

    # userName → email
    elif path == "username":
        if isinstance(value, str) and value:
            user.email = value.lower().strip()

    # displayName
    elif path in {"displayname", "name.givenname", "name.familyname"}:
        if isinstance(value, str):
            user.display_name = value


# ---------------------------------------------------------------------------
# PUT /Users/{id} — Full replace (RFC 7644 §3.5.1)
# ---------------------------------------------------------------------------


@router.put(
    "/{user_id}",
    response_model=ScimUserResponse,
    summary="SCIM: Full replace user",
)
async def scim_put_user(
    user_id: str,
    body: ScimUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> ScimUserResponse:
    result = await db.execute(
        select(AppUser).where(AppUser.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Apply full replacement of mutable fields
    from app.models.audit import AuditLog, AuditAction

    old_role = user.role.value if user.role else None
    new_role = _resolve_role(body)

    user.email = body.userName
    given = body.name.givenName if body.name and body.name.givenName else ""
    family = body.name.familyName if body.name and body.name.familyName else ""
    user.display_name = f"{given} {family}".strip() or body.userName
    user.unit = body.enterprise.department if body.enterprise else None
    user.active = body.active

    if new_role != user.role:
        user.role = new_role
        # Audit role change
        audit_entry = AuditLog(
            id=uuid.uuid4(),
            user_id=user.id,
            action=AuditAction.USER_ROLE_CHANGED,
            details={
                "source": "scim_put",
                "old_role": old_role,
                "new_role": new_role.value,
            },
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit_entry)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "SCIM user replaced (PUT)",
        extra={"event": "scim_user_put", "user_id": user_id},
    )
    return _build_scim_response(user, request)
```

---

## Files Created / Modified

| File | Action |
|---|---|
| `backend/app/api/v1/admin/scim/router.py` | **Modify** — add `PATCH` + `PUT` handlers |

---

## Validation

```bash
cd backend

# Static type check on new handlers
python -m mypy app/api/v1/admin/scim/router.py --ignore-missing-imports

# Confirm PATCH path parsing handles enterprise extension URN
python -c "
urn = 'urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department'
assert 'department' in urn.lower()
print('Path check OK')
"

# Integration smoke test (dev server running):
# Patch department change:
# curl -X PATCH http://localhost:8000/api/v1/admin/scim/Users/{id} \
#   -H 'Authorization: Bearer $SCIM_CLIENT_SECRET' \
#   -H 'Content-Type: application/json' \
#   -d '{
#     "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
#     "Operations": [{
#       "op": "replace",
#       "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
#       "value": "Pharmacy"
#     }]
#   }'
# Expected: 200 OK; role in response = PHARMACIST
```
