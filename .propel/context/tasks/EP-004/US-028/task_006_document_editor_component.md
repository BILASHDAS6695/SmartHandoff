---
id: TASK-006
title: "Implement Angular `DocumentEditorComponent` with Quill, Auto-Save Debounce, and Approve/Reject Actions"
user_story: US-028
epic: EP-004
sprint: 2
layer: Frontend — Component
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Frontend Engineer
upstream: [TASK-001, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Implement Angular `DocumentEditorComponent` with Quill, Auto-Save, and Actions

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Frontend — Component | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `DocumentEditorComponent` is the right-pane editor. It owns:

1. **Quill rich-text editor** (`ngx-quill`) — one Quill instance per document section
2. **Auto-save** — 2-second debounce on content change → emits `saveDraft` output event
3. **Diff computation** — client-side field comparison against `aiDraft` to produce the diff payload
4. **Approve / Reject action buttons** — role-gated visibility (physician-only for Approve)
5. **Document service calls** — `saveDraft`, `approveDocument`, `rejectDocument`

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 1** | Editable right pane with structured section editing |
| **Scenario 2** | 2-second debounced auto-save → diff payload emitted |
| **Scenario 3** | "Save Draft" button persists content; status remains `PENDING_REVIEW` |
| **Scenario 4** | "Approve" button visible only to physician role; "Reject" to all reviewers |

---

## Implementation Steps

### 1. Create `document-editor.component.ts`

```typescript
/**
 * DocumentEditorComponent
 *
 * Right-pane editable document editor for the dual-pane review UI (US-028).
 *
 * Auto-save: content changes are debounced 2 s then emitted via `(saveDraft)`.
 * Diff: client-side field comparison against the immutable AI draft.
 * Role gating: Approve button rendered only when `userRole === 'physician'`.
 */
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { QuillModule } from 'ngx-quill';
import {
  Subject,
  debounceTime,
  distinctUntilChanged,
  takeUntil,
} from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { DocumentService } from '../services/document.service';
import { RejectDialogComponent } from '../reject-dialog/reject-dialog.component';
import { computeClientDiff } from '../utils/document-diff.util';

/** Payload emitted on every debounced auto-save. */
export interface SaveDraftPayload {
  content: Record<string, string>;
  diff: Record<string, { old_value: unknown; new_value: unknown }>;
}

@Component({
  selector: 'sh-document-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatProgressSpinnerModule,
    QuillModule,
  ],
  templateUrl: './document-editor.component.html',
  styleUrl: './document-editor.component.scss',
})
export class DocumentEditorComponent implements OnInit, OnDestroy {
  /** ID of the document being edited. */
  @Input({ required: true }) documentId!: string;
  /** Current editable content (may already differ from AI draft if previously edited). */
  @Input({ required: true }) initialContent!: Record<string, string>;
  /** Immutable AI-generated draft — used as baseline for diff computation. */
  @Input({ required: true }) aiDraft!: Record<string, string>;
  /** Forwarded saving indicator from parent to disable Save Draft during in-flight request. */
  @Input() isSaving = false;

  /** Emits on every 2-second debounced auto-save. Parent calls the API. */
  @Output() saveDraft = new EventEmitter<SaveDraftPayload>();

  private readonly auth = inject(AuthService);
  private readonly documentService = inject(DocumentService);
  private readonly dialog = inject(MatDialog);
  private readonly destroy$ = new Subject<void>();
  private readonly contentChange$ = new Subject<Record<string, string>>();

  /** Current mutable working copy of the document sections. */
  editableContent!: Record<string, string>;

  /** Section keys derived from initialContent for ngFor rendering. */
  sectionKeys: string[] = [];

  /** True when current user has physician role — gates Approve button. */
  isPhysician = false;

  readonly quillModules = {
    toolbar: [
      ['bold', 'italic', 'underline'],
      [{ list: 'ordered' }, { list: 'bullet' }],
      ['clean'],
    ],
  };

  ngOnInit(): void {
    this.editableContent = { ...this.initialContent };
    this.sectionKeys = Object.keys(this.initialContent);
    this.isPhysician = this.auth.currentUserRole === 'physician';

    // Auto-save: 2-second debounce on any content change (Scenario 2)
    this.contentChange$
      .pipe(debounceTime(2000), distinctUntilChanged(), takeUntil(this.destroy$))
      .subscribe((content) => {
        const diff = computeClientDiff(this.aiDraft, content);
        if (Object.keys(diff).length > 0) {
          this.saveDraft.emit({ content, diff });
        }
      });
  }

  onSectionChange(sectionKey: string, newValue: string): void {
    this.editableContent = { ...this.editableContent, [sectionKey]: newValue };
    this.contentChange$.next({ ...this.editableContent });
  }

  onSaveDraftClick(): void {
    // Immediate save on button click (bypasses debounce)
    const diff = computeClientDiff(this.aiDraft, this.editableContent);
    this.saveDraft.emit({ content: { ...this.editableContent }, diff });
  }

  onApproveClick(): void {
    this.documentService
      .approveDocument(this.documentId, {})
      .pipe(takeUntil(this.destroy$))
      .subscribe();
  }

  onRejectClick(): void {
    const ref = this.dialog.open(RejectDialogComponent, { width: '480px' });
    ref.afterClosed().pipe(takeUntil(this.destroy$)).subscribe((reason: string | undefined) => {
      if (reason) {
        this.documentService
          .rejectDocument(this.documentId, { rejection_reason: reason })
          .pipe(takeUntil(this.destroy$))
          .subscribe();
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
```

### 2. Create `document-editor.component.html`

```html
<!-- document-editor.component.html -->
<div class="editor-shell">

  <!-- Quill editor per section -->
  <div
    *ngFor="let key of sectionKeys"
    class="section-block"
    [attr.data-section]="key"
  >
    <h3 class="section-block__label">{{ key | titlecase }}</h3>
    <quill-editor
      [ngModel]="editableContent[key]"
      (ngModelChange)="onSectionChange(key, $event)"
      [modules]="quillModules"
      [placeholder]="'Edit ' + (key | titlecase)"
      [attr.aria-label]="'Edit section: ' + (key | titlecase)"
      format="text"
      theme="snow"
    />
  </div>

  <!-- Action bar -->
  <div class="editor-actions" role="toolbar" aria-label="Document actions">

    <button
      mat-stroked-button
      color="primary"
      type="button"
      [disabled]="isSaving"
      (click)="onSaveDraftClick()"
      aria-label="Save draft"
    >
      <span *ngIf="!isSaving">Save Draft</span>
      <mat-progress-spinner
        *ngIf="isSaving"
        mode="indeterminate"
        diameter="18"
        aria-label="Saving…"
      />
    </button>

    <!-- Reject: visible to all reviewer roles -->
    <button
      mat-stroked-button
      color="warn"
      type="button"
      (click)="onRejectClick()"
      aria-label="Reject document"
    >
      Reject
    </button>

    <!-- Approve: visible to physician role only (Scenario 4) -->
    <button
      *ngIf="isPhysician"
      mat-flat-button
      color="primary"
      type="button"
      (click)="onApproveClick()"
      aria-label="Approve document"
    >
      Approve
    </button>

  </div>

</div>
```

### 3. Create `frontend/src/app/features/documents/utils/document-diff.util.ts`

```typescript
/**
 * Client-side field-level diff utility for DocumentEditorComponent.
 *
 * Mirrors the backend `compute_field_diff` logic for client-side optimistic diff
 * computation before the API call. Compares top-level keys only.
 *
 * @param baseline  The immutable AI draft content (reference)
 * @param edited    The current edited content
 * @returns  Diff map: { fieldKey: { old_value, new_value } } for changed fields only
 */
export function computeClientDiff(
  baseline: Record<string, unknown>,
  edited: Record<string, unknown>,
): Record<string, { old_value: unknown; new_value: unknown }> {
  const diff: Record<string, { old_value: unknown; new_value: unknown }> = {};
  const allKeys = new Set([...Object.keys(baseline), ...Object.keys(edited)]);

  for (const key of allKeys) {
    const oldVal = baseline[key] ?? null;
    const newVal = edited[key] ?? null;
    if (oldVal !== newVal) {
      diff[key] = { old_value: oldVal, new_value: newVal };
    }
  }

  return diff;
}
```

### 4. Create `reject-dialog.component.ts` (stub for Reject confirmation modal)

```typescript
/**
 * RejectDialogComponent
 *
 * Modal dialog that collects a mandatory rejection reason before calling the reject API.
 * Closes with the reason string on confirm, or undefined on cancel.
 */
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

@Component({
  selector: 'sh-reject-dialog',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatDialogModule, MatFormFieldModule, MatInputModule],
  template: `
    <h2 mat-dialog-title>Reject Document</h2>
    <mat-dialog-content>
      <mat-form-field appearance="outline" class="full-width">
        <mat-label>Rejection reason</mat-label>
        <textarea
          matInput
          [(ngModel)]="reason"
          rows="4"
          maxlength="2000"
          aria-label="Rejection reason"
          placeholder="Describe the reason for rejection (required, min 10 characters)…"
        ></textarea>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-stroked-button mat-dialog-close aria-label="Cancel rejection">Cancel</button>
      <button
        mat-flat-button
        color="warn"
        [disabled]="reason.length < 10"
        [mat-dialog-close]="reason"
        aria-label="Confirm rejection"
      >
        Confirm Reject
      </button>
    </mat-dialog-actions>
  `,
  styles: ['.full-width { width: 100%; }'],
})
export class RejectDialogComponent {
  reason = '';
  constructor(public dialogRef: MatDialogRef<RejectDialogComponent>) {}
}
```

---

## File Locations

| File | Path |
|---|---|
| `document-editor.component.ts` | `frontend/src/app/features/documents/document-editor/document-editor.component.ts` |
| `document-editor.component.html` | `frontend/src/app/features/documents/document-editor/document-editor.component.html` |
| `document-diff.util.ts` | `frontend/src/app/features/documents/utils/document-diff.util.ts` |
| `reject-dialog.component.ts` | `frontend/src/app/features/documents/reject-dialog/reject-dialog.component.ts` |

---

## Validation Checklist

- [ ] Auto-save fires exactly after 2 000 ms of inactivity (debounce on `contentChange$`)
- [ ] `saveDraft` output is NOT emitted when diff is empty (no changes from AI draft)
- [ ] `isPhysician` is derived from `AuthService.currentUserRole` — not hardcoded
- [ ] "Approve" button not rendered in DOM for non-physician users (`*ngIf`, not `[hidden]`)
- [ ] "Reject" button opens `RejectDialogComponent` modal before calling the API
- [ ] `RejectDialogComponent` confirm button disabled until `reason.length >= 10`
- [ ] `computeClientDiff` returns empty object when baseline equals edited
- [ ] `ngx-quill` modules restrict toolbar to bold/italic/underline/lists/clear only
- [ ] All subscriptions cleaned up via `takeUntil(this.destroy$)` in `ngOnDestroy`
- [ ] `ChangeDetectionStrategy.OnPush` applied

---

## Dependencies

| Dependency | Notes |
|---|---|
| `ngx-quill` | `npm install ngx-quill quill` — add to `package.json` |
| `TASK-005` | Parent `DocumentReviewComponent` receives `saveDraft` output |
| `TASK-003` | `DocumentService.saveDraft()` method |
| `TASK-004` | `DocumentService.approveDocument()` / `rejectDocument()` methods |
