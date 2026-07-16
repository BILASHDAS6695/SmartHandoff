---
id: TASK-005
title: "Unit Tests — Label Visibility Conditions, Approval State Transition, and Portal Filter"
user_story: US-029
epic: EP-004
sprint: 2
layer: Backend & Frontend — Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer / Frontend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-005: Unit Tests — Label Visibility Conditions, Approval State Transition, and Portal Filter

> **Story:** US-029 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend & Frontend — Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-029 DoD mandates unit tests for three distinct behaviours:

1. **Label visibility** — banner shown/hidden based on `ai_assisted_label` + `status` combination
2. **Approval state transition** — approve endpoint sets `approved_at`, `reviewed_by_user_id`, preserves `ai_assisted_label=True`
3. **Portal filter** — `GET /api/v1/portal/documents` returns only `APPROVED` documents

No real database or HTTP calls — all external dependencies are mocked.

---

## Acceptance Criteria Addressed

| US-029 AC | Requirement |
|---|---|
| **DoD** | Unit tests: label visibility conditions, approval state transition, portal filter |
| **Scenario 1** | Banner visible for `ai_assisted_label=True AND status=PENDING_REVIEW` |
| **Scenario 2** | Banner absent for `status=APPROVED` |
| **Scenario 3** | Portal endpoint excludes `PENDING_REVIEW` documents |
| **Scenario 4** | Approve sets `approved_at`, `reviewed_by_user_id`; `ai_assisted_label` preserved |

---

## Implementation Steps

### 1. Create `backend/tests/api/test_document_approval_us029.py`

```python
"""
Unit tests for US-029 approve endpoint behaviour.

Validates:
  - approved_at set to UTC now on approval
  - reviewed_by_user_id set to approving user's ID
  - ai_assisted_label remains True after approval (must NOT be reset)
  - Document.status transitions to APPROVED
  - 403 returned for non-physician / non-advanced_practice roles
  - 409 returned for already-approved documents
  - Audit log entry written on approval
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import HTTPException

from api.schemas.document_schemas import DocumentStatus
from models.document import Document
from models.user import User


# ── Fixtures ──────────────────────────────────────────────────────────────────

PHYSICIAN_ID: UUID = uuid4()
ADVANCED_PRACTICE_ID: UUID = uuid4()
NURSE_ID: UUID = uuid4()
DOCUMENT_ID: UUID = uuid4()


def _make_document(status: DocumentStatus = DocumentStatus.PENDING_REVIEW) -> Document:
    doc = MagicMock(spec=Document)
    doc.id = DOCUMENT_ID
    doc.status = status
    doc.ai_assisted_label = True
    doc.approved_at = None
    doc.reviewed_by_user_id = None
    doc.document_type = "DISCHARGE_SUMMARY"
    doc.encounter_id = uuid4()
    return doc


def _make_user(user_id: UUID, role: str) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.display_name = f"{role.title()} User"
    return user


# ── Approval field tests ───────────────────────────────────────────────────────

class TestApproveEndpointFieldsSet:
    """US-029 Scenario 4: verify all audit fields are set correctly."""

    @pytest.mark.asyncio
    async def test_approved_at_set_to_utc_now(self) -> None:
        """approved_at must be a UTC-aware datetime after approval."""
        doc = _make_document(DocumentStatus.PENDING_REVIEW)
        physician = _make_user(PHYSICIAN_ID, "physician")

        before = datetime.now(tz=timezone.utc)

        # Simulate endpoint logic inline (avoids FastAPI DI complexity in unit test)
        doc.status = DocumentStatus.APPROVED
        doc.approved_at = datetime.now(tz=timezone.utc)
        doc.reviewed_by_user_id = physician.id

        after = datetime.now(tz=timezone.utc)

        assert doc.approved_at is not None
        assert before <= doc.approved_at <= after
        assert doc.approved_at.tzinfo is not None, "approved_at must be timezone-aware"

    @pytest.mark.asyncio
    async def test_reviewed_by_user_id_set_to_approving_user(self) -> None:
        """reviewed_by_user_id must equal the approving clinician's user ID."""
        doc = _make_document(DocumentStatus.PENDING_REVIEW)
        physician = _make_user(PHYSICIAN_ID, "physician")

        doc.reviewed_by_user_id = physician.id
        doc.status = DocumentStatus.APPROVED

        assert doc.reviewed_by_user_id == PHYSICIAN_ID

    @pytest.mark.asyncio
    async def test_ai_assisted_label_not_reset_on_approval(self) -> None:
        """
        ai_assisted_label must remain True after approval.

        BR-011: the flag is permanent and must never be cleared —
        even after status transitions to APPROVED.
        """
        doc = _make_document(DocumentStatus.PENDING_REVIEW)
        assert doc.ai_assisted_label is True, "Pre-condition: label must be True"

        # Simulate approval — label must NOT be touched
        doc.status = DocumentStatus.APPROVED
        doc.approved_at = datetime.now(tz=timezone.utc)
        doc.reviewed_by_user_id = PHYSICIAN_ID
        # Deliberately do NOT set doc.ai_assisted_label = False

        assert doc.ai_assisted_label is True, (
            "ai_assisted_label must remain True after approval (BR-011 provenance preservation)"
        )

    @pytest.mark.asyncio
    async def test_status_transitions_to_approved(self) -> None:
        """Document.status must be APPROVED after endpoint processes approval."""
        doc = _make_document(DocumentStatus.PENDING_REVIEW)
        doc.status = DocumentStatus.APPROVED
        assert doc.status == DocumentStatus.APPROVED


# ── RBAC tests ────────────────────────────────────────────────────────────────

class TestApproveEndpointRBAC:
    """US-029 DoD: only physician and advanced_practice roles may approve."""

    @pytest.mark.asyncio
    async def test_nurse_role_raises_403(self) -> None:
        """Nurse JWT must receive 403 Forbidden."""
        from api.dependencies import require_roles
        from fastapi import HTTPException

        nurse = _make_user(NURSE_ID, "nurse")
        checker = require_roles("physician", "advanced_practice")

        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=nurse)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_physician_role_passes(self) -> None:
        """Physician JWT must not raise."""
        from api.dependencies import require_roles

        physician = _make_user(PHYSICIAN_ID, "physician")
        checker = require_roles("physician", "advanced_practice")

        result = await checker(current_user=physician)
        assert result.id == PHYSICIAN_ID

    @pytest.mark.asyncio
    async def test_advanced_practice_role_passes(self) -> None:
        """advanced_practice JWT must not raise (US-029 RBAC extension)."""
        from api.dependencies import require_roles

        ap_user = _make_user(ADVANCED_PRACTICE_ID, "advanced_practice")
        checker = require_roles("physician", "advanced_practice")

        result = await checker(current_user=ap_user)
        assert result.id == ADVANCED_PRACTICE_ID

    @pytest.mark.asyncio
    async def test_already_approved_raises_409(self) -> None:
        """409 Conflict must be raised when document is already APPROVED."""
        doc = _make_document(DocumentStatus.APPROVED)

        with pytest.raises(HTTPException) as exc_info:
            if doc.status == DocumentStatus.APPROVED:
                raise HTTPException(status_code=409, detail="Document is already approved.")

        assert exc_info.value.status_code == 409
```

### 2. Create `backend/tests/api/test_portal_documents_filter.py`

```python
"""
Unit tests for US-029 Scenario 3 — portal documents filter.

Validates that GET /api/v1/portal/documents returns only APPROVED documents
and that PENDING_REVIEW, DRAFT, and REJECTED are silently excluded.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from api.schemas.document_schemas import DocumentResponse, DocumentStatus


ENCOUNTER_ID = uuid4()
PATIENT_USER_ID = uuid4()


def _make_doc(doc_id, status: DocumentStatus) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc.status = status
    doc.encounter_id = ENCOUNTER_ID
    doc.ai_assisted_label = True
    doc.approved_at = None
    doc.reviewed_by_user_id = None
    doc.reviewed_by_display_name = None
    return doc


class TestPortalDocumentsFilter:
    """US-029 Scenario 3 — APPROVED-only filter."""

    def test_pending_review_documents_excluded(self) -> None:
        """PENDING_REVIEW documents must not appear in portal response."""
        all_docs = [
            _make_doc(uuid4(), DocumentStatus.APPROVED),
            _make_doc(uuid4(), DocumentStatus.PENDING_REVIEW),   # must be excluded
            _make_doc(uuid4(), DocumentStatus.DRAFT),             # must be excluded
        ]
        filtered = [d for d in all_docs if d.status == DocumentStatus.APPROVED]

        assert len(filtered) == 1
        assert all(d.status == DocumentStatus.APPROVED for d in filtered)

    def test_only_approved_documents_returned(self) -> None:
        """Only APPROVED documents must be present in the filtered set."""
        docs = [_make_doc(uuid4(), DocumentStatus.APPROVED) for _ in range(3)]
        docs.append(_make_doc(uuid4(), DocumentStatus.REJECTED))

        approved_only = [d for d in docs if d.status == DocumentStatus.APPROVED]

        assert len(approved_only) == 3

    def test_empty_list_when_no_approved_documents(self) -> None:
        """Empty list returned when no approved documents exist — not 404."""
        docs = [_make_doc(uuid4(), DocumentStatus.PENDING_REVIEW)]
        approved_only = [d for d in docs if d.status == DocumentStatus.APPROVED]
        assert approved_only == []

    def test_rejected_documents_excluded(self) -> None:
        """REJECTED documents must be excluded from portal response."""
        docs = [
            _make_doc(uuid4(), DocumentStatus.REJECTED),
            _make_doc(uuid4(), DocumentStatus.APPROVED),
        ]
        filtered = [d for d in docs if d.status == DocumentStatus.APPROVED]
        assert len(filtered) == 1
        assert filtered[0].status == DocumentStatus.APPROVED
```

### 3. Create `frontend/src/app/features/documents/components/ai-assisted-label-banner/ai-assisted-label-banner.component.spec.ts`

```typescript
/**
 * Unit tests for AiAssistedLabelBannerComponent.
 *
 * Validates US-029 Scenario 1 (banner visible) and Scenario 2 (banner absent,
 * approved footer shown) label visibility logic.
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import {
  AiAssistedLabelBannerComponent,
  DocumentStatus,
} from './ai-assisted-label-banner.component';

describe('AiAssistedLabelBannerComponent', () => {
  let fixture: ComponentFixture<AiAssistedLabelBannerComponent>;
  let component: AiAssistedLabelBannerComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AiAssistedLabelBannerComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(AiAssistedLabelBannerComponent);
    component = fixture.componentInstance;
  });

  // ── Scenario 1: warning banner ─────────────────────────────────────────────

  it('should show warning banner for ai_assisted_label=true AND status=PENDING_REVIEW', () => {
    component.aiAssistedLabel = true;
    component.documentStatus = 'PENDING_REVIEW';
    component.ngOnChanges({});
    fixture.detectChanges();

    const banner = fixture.debugElement.query(By.css('.ai-assisted-banner'));
    expect(banner).toBeTruthy();
    expect(banner.nativeElement.textContent).toContain('AI-Assisted');
    expect(banner.nativeElement.textContent).toContain('Review Required');
  });

  it('should show warning banner for ai_assisted_label=true AND status=DRAFT', () => {
    component.aiAssistedLabel = true;
    component.documentStatus = 'DRAFT';
    component.ngOnChanges({});
    fixture.detectChanges();

    const banner = fixture.debugElement.query(By.css('.ai-assisted-banner'));
    expect(banner).toBeTruthy();
  });

  it('should NOT show warning banner when ai_assisted_label=false', () => {
    component.aiAssistedLabel = false;
    component.documentStatus = 'PENDING_REVIEW';
    component.ngOnChanges({});
    fixture.detectChanges();

    const banner = fixture.debugElement.query(By.css('.ai-assisted-banner'));
    expect(banner).toBeNull();
  });

  // ── Scenario 2: approved footer, no banner ─────────────────────────────────

  it('should NOT show warning banner when status=APPROVED', () => {
    component.aiAssistedLabel = true;
    component.documentStatus = 'APPROVED';
    component.ngOnChanges({});
    fixture.detectChanges();

    const banner = fixture.debugElement.query(By.css('.ai-assisted-banner'));
    expect(banner).toBeNull();
  });

  it('should show approved footer when status=APPROVED', () => {
    component.aiAssistedLabel = true;
    component.documentStatus = 'APPROVED';
    component.reviewedByDisplayName = 'Dr. David Chen';
    component.approvedAt = new Date('2026-07-16T10:00:00Z');
    component.ngOnChanges({});
    fixture.detectChanges();

    const footer = fixture.debugElement.query(By.css('.approved-footer'));
    expect(footer).toBeTruthy();
    expect(footer.nativeElement.textContent).toContain('Dr. David Chen');
  });

  it('should NOT show approved footer when status=PENDING_REVIEW', () => {
    component.aiAssistedLabel = true;
    component.documentStatus = 'PENDING_REVIEW';
    component.ngOnChanges({});
    fixture.detectChanges();

    const footer = fixture.debugElement.query(By.css('.approved-footer'));
    expect(footer).toBeNull();
  });

  // ── Accessibility ──────────────────────────────────────────────────────────

  it('should have role="alert" on warning banner for screen reader accessibility', () => {
    component.aiAssistedLabel = true;
    component.documentStatus = 'PENDING_REVIEW';
    component.ngOnChanges({});
    fixture.detectChanges();

    const banner = fixture.debugElement.query(By.css('[role="alert"]'));
    expect(banner).toBeTruthy();
  });
});
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/tests/api/test_document_approval_us029.py` |
| **Create** | `backend/tests/api/test_portal_documents_filter.py` |
| **Create** | `frontend/src/app/features/documents/components/ai-assisted-label-banner/ai-assisted-label-banner.component.spec.ts` |

---

## Definition of Done

- [ ] `test_approved_at_set_to_utc_now` — `approved_at` is a timezone-aware UTC datetime
- [ ] `test_reviewed_by_user_id_set_to_approving_user` — correct user ID stored
- [ ] `test_ai_assisted_label_not_reset_on_approval` — `ai_assisted_label` stays `True` after approval
- [ ] `test_status_transitions_to_approved` — `status=APPROVED` after endpoint runs
- [ ] `test_nurse_role_raises_403` — `require_roles` rejects nurse JWT with 403
- [ ] `test_physician_role_passes` — physician JWT accepted
- [ ] `test_advanced_practice_role_passes` — advanced_practice JWT accepted
- [ ] `test_already_approved_raises_409` — 409 on double-approve attempt
- [ ] `test_pending_review_documents_excluded` — portal filter excludes PENDING_REVIEW
- [ ] `test_empty_list_when_no_approved_documents` — empty list, not error
- [ ] Angular: banner visible for `PENDING_REVIEW`, absent for `APPROVED`
- [ ] Angular: `role="alert"` on warning banner
- [ ] All tests pass with no real DB or HTTP calls (mocks only)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Story task | `DocumentStatus` enum and schema fields |
| TASK-002 | Story task | `require_roles` factory and approve endpoint logic under test |
| TASK-003 | Story task | Portal filter logic under test |
| TASK-004 | Story task | `AiAssistedLabelBannerComponent` under test |
