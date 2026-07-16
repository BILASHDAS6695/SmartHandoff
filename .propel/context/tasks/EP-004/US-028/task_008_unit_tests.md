---
id: TASK-008
title: "Unit Tests — Diff Engine, RBAC Enforcement, and Auto-Save Debounce"
user_story: US-028
epic: EP-004
sprint: 2
layer: Backend & Frontend — Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer / Frontend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-006]
---

# TASK-008: Unit Tests — Diff Engine, RBAC Enforcement, and Auto-Save Debounce

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend & Frontend — Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 DoD mandates verified acceptance criteria across all four scenarios. This task delivers:

1. **Backend pytest** — `compute_field_diff`, `apply_diff_to_change_log`, approve RBAC (403 for nurse), reject open access
2. **Frontend Jest** — `computeClientDiff` utility, 2-second debounce behaviour, Approve button visibility gate

No real DB or API calls — all external dependencies mocked.

---

## Acceptance Criteria Addressed

All four US-028 scenarios validated by unit tests.

---

## Implementation Steps

### 1. Create `tests/services/test_document_diff.py`

```python
"""
Unit tests for the document_diff service module.

Validates field-level diff detection, append-only log behaviour, and edge cases.
"""
import pytest
from uuid import UUID, uuid4
from datetime import timezone

from api.schemas.document_schemas import ChangeLogEntry
from services.document_diff import compute_field_diff, apply_diff_to_change_log

AUTHOR_ID: UUID = uuid4()


class TestComputeFieldDiff:
    """Tests for compute_field_diff()."""

    def test_no_changes_returns_empty_list(self) -> None:
        stored = {"medications": "Aspirin 100mg", "diet": "Low sodium"}
        updated = {"medications": "Aspirin 100mg", "diet": "Low sodium"}
        result = compute_field_diff(stored, updated, AUTHOR_ID)
        assert result == []

    def test_single_field_change_produces_one_entry(self) -> None:
        stored = {"medications": "Aspirin 100mg"}
        updated = {"medications": "Aspirin 75mg"}
        entries = compute_field_diff(stored, updated, AUTHOR_ID)
        assert len(entries) == 1
        assert entries[0].field == "medications"
        assert entries[0].old_value == "Aspirin 100mg"
        assert entries[0].new_value == "Aspirin 75mg"
        assert entries[0].author_id == AUTHOR_ID

    def test_multiple_fields_changed_produces_multiple_entries(self) -> None:
        stored = {"medications": "Aspirin", "diet": "Normal", "activity": "Rest"}
        updated = {"medications": "Warfarin", "diet": "Low sodium", "activity": "Rest"}
        entries = compute_field_diff(stored, updated, AUTHOR_ID)
        changed_fields = {e.field for e in entries}
        assert changed_fields == {"medications", "diet"}
        assert len(entries) == 2

    def test_new_field_added_produces_entry_with_none_old_value(self) -> None:
        stored: dict = {}
        updated = {"medications": "New med"}
        entries = compute_field_diff(stored, updated, AUTHOR_ID)
        assert len(entries) == 1
        assert entries[0].old_value is None
        assert entries[0].new_value == "New med"

    def test_field_removed_produces_entry_with_none_new_value(self) -> None:
        stored = {"medications": "Aspirin"}
        updated: dict = {}
        entries = compute_field_diff(stored, updated, AUTHOR_ID)
        assert len(entries) == 1
        assert entries[0].old_value == "Aspirin"
        assert entries[0].new_value is None

    def test_timestamp_is_timezone_aware_utc(self) -> None:
        stored = {"medications": "Old"}
        updated = {"medications": "New"}
        entries = compute_field_diff(stored, updated, AUTHOR_ID)
        assert entries[0].timestamp.tzinfo is not None
        assert entries[0].timestamp.tzinfo == timezone.utc

    def test_raises_value_error_for_non_dict_stored(self) -> None:
        with pytest.raises(ValueError, match="stored_content must be a dict"):
            compute_field_diff("not a dict", {}, AUTHOR_ID)  # type: ignore

    def test_raises_value_error_for_non_dict_updated(self) -> None:
        with pytest.raises(ValueError, match="updated_content must be a dict"):
            compute_field_diff({}, 42, AUTHOR_ID)  # type: ignore

    def test_entries_ordered_by_field_name(self) -> None:
        """Entries must be sorted by field key for deterministic audit trails."""
        stored = {"z_field": "old", "a_field": "old"}
        updated = {"z_field": "new", "a_field": "new"}
        entries = compute_field_diff(stored, updated, AUTHOR_ID)
        assert entries[0].field == "a_field"
        assert entries[1].field == "z_field"


class TestApplyDiffToChangeLog:
    """Tests for apply_diff_to_change_log()."""

    def _make_entry(self) -> ChangeLogEntry:
        return ChangeLogEntry(
            field="medications",
            old_value="Aspirin",
            new_value="Warfarin",
            author_id=AUTHOR_ID,
        )

    def test_appends_to_empty_log(self) -> None:
        entry = self._make_entry()
        result = apply_diff_to_change_log([], [entry])
        assert len(result) == 1
        assert result[0]["field"] == "medications"

    def test_appends_to_existing_log(self) -> None:
        existing = [{"field": "diet", "old_value": "a", "new_value": "b",
                     "author_id": str(AUTHOR_ID), "timestamp": "2026-07-16T00:00:00Z"}]
        entry = self._make_entry()
        result = apply_diff_to_change_log(existing, [entry])
        assert len(result) == 2
        assert result[0]["field"] == "diet"
        assert result[1]["field"] == "medications"

    def test_does_not_mutate_existing_log(self) -> None:
        existing: list[dict] = []
        entry = self._make_entry()
        apply_diff_to_change_log(existing, [entry])
        assert existing == []  # Original list unchanged

    def test_empty_new_entries_returns_copy_of_existing(self) -> None:
        existing = [{"field": "diet"}]
        result = apply_diff_to_change_log(existing, [])
        assert result == existing
        assert result is not existing  # New list object
```

### 2. Create `tests/api/test_document_rbac.py`

```python
"""
RBAC unit tests for the document approve and reject endpoints.

Uses FastAPI TestClient with mocked DB session and JWT claims.
Validates Scenario 4: nurse JWT → 403 on approve; all roles can reject.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from main import app  # FastAPI app instance
from models.document import Document
from api.schemas.document_schemas import DocumentStatus

DOCUMENT_ID = str(uuid4())

# Fixtures simulating different JWT role payloads
@pytest.fixture
def physician_headers() -> dict:
    return {"Authorization": "Bearer physician-test-token"}

@pytest.fixture
def nurse_headers() -> dict:
    return {"Authorization": "Bearer nurse-test-token"}


class TestApproveEndpointRBAC:
    """Scenario 4: approve is restricted to physician role."""

    @patch("api.routers.documents.get_document_or_404")
    @patch("api.dependencies.get_current_user")
    def test_physician_can_approve(
        self, mock_user, mock_get_doc, physician_headers
    ) -> None:
        mock_user.return_value = MagicMock(id=uuid4(), role="physician")
        mock_doc = MagicMock(spec=Document)
        mock_doc.status = DocumentStatus.PENDING_REVIEW
        mock_doc.metadata = {}
        mock_get_doc.return_value = mock_doc

        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/documents/{DOCUMENT_ID}/approve",
                json={},
                headers=physician_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == DocumentStatus.APPROVED

    @patch("api.dependencies.get_current_user")
    def test_nurse_receives_403_on_approve(
        self, mock_user, nurse_headers
    ) -> None:
        mock_user.return_value = MagicMock(id=uuid4(), role="nurse")

        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/documents/{DOCUMENT_ID}/approve",
                json={},
                headers=nurse_headers,
            )
        assert resp.status_code == 403
        assert "not authorised" in resp.json()["detail"].lower()

    @patch("api.routers.documents.get_document_or_404")
    @patch("api.dependencies.get_current_user")
    def test_nurse_can_reject(
        self, mock_user, mock_get_doc, nurse_headers
    ) -> None:
        mock_user.return_value = MagicMock(id=uuid4(), role="nurse")
        mock_doc = MagicMock(spec=Document)
        mock_doc.status = DocumentStatus.PENDING_REVIEW
        mock_doc.metadata = {}
        mock_get_doc.return_value = mock_doc

        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/documents/{DOCUMENT_ID}/reject",
                json={"rejection_reason": "Missing discharge medications list."},
                headers=nurse_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == DocumentStatus.REJECTED

    @patch("api.dependencies.get_current_user")
    def test_reject_without_reason_returns_422(
        self, mock_user, nurse_headers
    ) -> None:
        mock_user.return_value = MagicMock(id=uuid4(), role="nurse")

        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/documents/{DOCUMENT_ID}/reject",
                json={},
                headers=nurse_headers,
            )
        assert resp.status_code == 422
```

### 3. Create `frontend/src/app/features/documents/utils/document-diff.util.spec.ts`

```typescript
/**
 * Unit tests for computeClientDiff utility (US-028 Scenario 2).
 */
import { computeClientDiff } from './document-diff.util';

describe('computeClientDiff', () => {
  it('returns empty object when baseline equals edited', () => {
    const baseline = { medications: 'Aspirin', diet: 'Normal' };
    const result = computeClientDiff(baseline, { ...baseline });
    expect(result).toEqual({});
  });

  it('returns diff entry for changed field', () => {
    const baseline = { medications: 'Aspirin' };
    const edited = { medications: 'Warfarin' };
    const result = computeClientDiff(baseline, edited);
    expect(result).toEqual({
      medications: { old_value: 'Aspirin', new_value: 'Warfarin' },
    });
  });

  it('returns entry with null old_value for newly added field', () => {
    const result = computeClientDiff({}, { follow_up: 'Call Dr Smith' });
    expect(result['follow_up'].old_value).toBeNull();
    expect(result['follow_up'].new_value).toBe('Call Dr Smith');
  });

  it('returns entry with null new_value for removed field', () => {
    const result = computeClientDiff({ diet: 'Low sodium' }, {});
    expect(result['diet'].old_value).toBe('Low sodium');
    expect(result['diet'].new_value).toBeNull();
  });

  it('handles multiple changed fields independently', () => {
    const baseline = { a: '1', b: '2', c: '3' };
    const edited = { a: 'changed', b: '2', c: 'changed' };
    const result = computeClientDiff(baseline, edited);
    expect(Object.keys(result)).toHaveLength(2);
    expect(result['a']).toBeDefined();
    expect(result['c']).toBeDefined();
    expect(result['b']).toBeUndefined();
  });
});
```

### 4. Create `document-editor.component.spec.ts` (auto-save debounce test)

```typescript
/**
 * Unit tests for DocumentEditorComponent auto-save debounce (US-028 Scenario 2).
 */
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { DocumentEditorComponent } from './document-editor.component';
import { DocumentService } from '../services/document.service';
import { AuthService } from '../../../core/auth/auth.service';
import { of } from 'rxjs';
import { QuillModule } from 'ngx-quill';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

describe('DocumentEditorComponent — auto-save', () => {
  let component: DocumentEditorComponent;
  let fixture: ComponentFixture<DocumentEditorComponent>;
  let saveDraftSpy: jest.SpyInstance;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentEditorComponent, QuillModule.forRoot(), NoopAnimationsModule],
      providers: [
        { provide: DocumentService, useValue: { saveDraft: jest.fn(() => of({})) } },
        { provide: AuthService, useValue: { currentUserRole: 'nurse' } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(DocumentEditorComponent);
    component = fixture.componentInstance;
    component.documentId = 'doc-123';
    component.initialContent = { medications: 'Aspirin' };
    component.aiDraft = { medications: 'Aspirin' };
    fixture.detectChanges();

    saveDraftSpy = jest.spyOn(component.saveDraft, 'emit');
  });

  it('does NOT emit saveDraft immediately on content change', fakeAsync(() => {
    component.onSectionChange('medications', 'Warfarin');
    tick(1000); // Less than debounce window
    expect(saveDraftSpy).not.toHaveBeenCalled();
  }));

  it('emits saveDraft after 2000ms debounce', fakeAsync(() => {
    component.onSectionChange('medications', 'Warfarin');
    tick(2000);
    expect(saveDraftSpy).toHaveBeenCalledTimes(1);
    const payload = saveDraftSpy.mock.calls[0][0];
    expect(payload.diff['medications']).toBeDefined();
  }));

  it('does NOT emit saveDraft when diff is empty (no change from AI draft)', fakeAsync(() => {
    component.onSectionChange('medications', 'Aspirin'); // Same as aiDraft
    tick(2000);
    expect(saveDraftSpy).not.toHaveBeenCalled();
  }));

  it('Approve button is NOT rendered for nurse role', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const approveBtn = compiled.querySelector('[aria-label="Approve document"]');
    expect(approveBtn).toBeNull();
  });

  it('Reject button IS rendered for nurse role', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const rejectBtn = compiled.querySelector('[aria-label="Reject document"]');
    expect(rejectBtn).not.toBeNull();
  });
});
```

---

## File Locations

| File | Path |
|---|---|
| `test_document_diff.py` | `backend/tests/services/test_document_diff.py` |
| `test_document_rbac.py` | `backend/tests/api/test_document_rbac.py` |
| `document-diff.util.spec.ts` | `frontend/src/app/features/documents/utils/document-diff.util.spec.ts` |
| `document-editor.component.spec.ts` | `frontend/src/app/features/documents/document-editor/document-editor.component.spec.ts` |

---

## Validation Checklist

- [ ] `compute_field_diff` — 8 backend test cases all green
- [ ] `apply_diff_to_change_log` — 4 backend test cases all green; no mutation of input list
- [ ] Nurse JWT → `403` on `PATCH /approve`; physician JWT → `200`
- [ ] Nurse JWT → `200` on `PATCH /reject` with valid reason
- [ ] `PATCH /reject` without body → `422`
- [ ] `computeClientDiff` — 5 frontend unit tests all green
- [ ] Auto-save debounce: emits after 2 000 ms, not before; skips emit when diff is empty
- [ ] Approve button absent from DOM for non-physician role
- [ ] No real HTTP calls or DB connections in any test

---

## Dependencies

| Dependency | Notes |
|---|---|
| `pytest`, `pytest-asyncio` | Already in project |
| `fastapi[testclient]` | `TestClient` for RBAC integration tests |
| `jest`, `@angular/core/testing` | Frontend unit testing framework |
| `TASK-002` | `compute_field_diff` and `apply_diff_to_change_log` must be implemented |
| `TASK-004` | Approve/reject endpoints must be implemented |
| `TASK-006` | `DocumentEditorComponent` and `computeClientDiff` must be implemented |
