---
id: TASK-005
title: "Implement Angular `DocumentReviewComponent` Dual-Pane Layout with Scroll Sync"
user_story: US-028
epic: EP-004
sprint: 2
layer: Frontend — Component
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Frontend Engineer
upstream: [TASK-001, TASK-003, TASK-004]
---

# TASK-005: Implement Angular `DocumentReviewComponent` Dual-Pane Layout with Scroll Sync

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Frontend — Component | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 Scenario 1 requires a dual-pane layout:
- **Left pane** — immutable AI-generated draft (`contenteditable=false`)
- **Right pane** — editable copy (Quill rich-text editor) pre-populated with the same content
- **Scroll synchronisation** — scrolling either pane mirrors `scrollTop` on the other (debounced 16 ms to align with 60 fps)

The component lives in `features/documents/` and is lazy-loaded. It receives the `documentId`
via route param, loads the document from the API, and subscribes to auto-save output events
from the child `DocumentEditorComponent` (TASK-006).

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 1** | Left pane read-only; right pane editable; both scroll in sync |
| **Scenario 3** | "Save Draft" button calls `PATCH /api/v1/documents/{id}` |

---

## Implementation Steps

### 1. Create `frontend/src/app/features/documents/document-review/document-review.component.ts`

```typescript
/**
 * DocumentReviewComponent
 *
 * Dual-pane document review UI (US-028 Scenario 1).
 * Left pane: read-only AI draft.  Right pane: editable copy with auto-save.
 * Both panes scroll in sync via ElementRef scroll event listeners.
 */
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
  inject,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import {
  Subject,
  debounceTime,
  distinctUntilChanged,
  fromEvent,
  switchMap,
  takeUntil,
} from 'rxjs';

import { DocumentService } from '../services/document.service';
import { DocumentEditorComponent } from '../document-editor/document-editor.component';
import { ChangeLogTimelineComponent } from '../change-log-timeline/change-log-timeline.component';
import { DocumentReviewVm } from '../models/document-review.vm';

@Component({
  selector: 'sh-document-review',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    DocumentEditorComponent,
    ChangeLogTimelineComponent,
  ],
  templateUrl: './document-review.component.html',
  styleUrl: './document-review.component.scss',
})
export class DocumentReviewComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('leftPane') leftPane!: ElementRef<HTMLDivElement>;
  @ViewChild('rightPane') rightPane!: ElementRef<HTMLDivElement>;

  private readonly route = inject(ActivatedRoute);
  private readonly documentService = inject(DocumentService);
  private readonly destroy$ = new Subject<void>();

  documentId!: string;
  vm: DocumentReviewVm | null = null;
  isSaving = false;

  /** Prevents scroll-sync feedback loop between the two panes. */
  private isScrollSyncing = false;

  ngOnInit(): void {
    this.documentId = this.route.snapshot.paramMap.get('id')!;
    this.documentService
      .getDocument(this.documentId)
      .pipe(takeUntil(this.destroy$))
      .subscribe((doc) => (this.vm = doc));
  }

  ngAfterViewInit(): void {
    this.initScrollSync(this.leftPane, this.rightPane);
    this.initScrollSync(this.rightPane, this.leftPane);
  }

  /**
   * Mirror scroll position from `source` to `target`.
   * Debounced at 16 ms (≈ 60 fps) to avoid jank.
   * Guard flag prevents the mirrored scroll from triggering a second sync.
   */
  private initScrollSync(
    source: ElementRef<HTMLDivElement>,
    target: ElementRef<HTMLDivElement>,
  ): void {
    fromEvent(source.nativeElement, 'scroll')
      .pipe(debounceTime(16), takeUntil(this.destroy$))
      .subscribe(() => {
        if (this.isScrollSyncing) return;
        this.isScrollSyncing = true;
        target.nativeElement.scrollTop = source.nativeElement.scrollTop;
        // Reset flag after browser repaints
        requestAnimationFrame(() => (this.isScrollSyncing = false));
      });
  }

  onSaveDraft(payload: { content: Record<string, unknown>; diff: Record<string, unknown> }): void {
    if (!this.documentId) return;
    this.isSaving = true;
    this.documentService
      .saveDraft(this.documentId, payload)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => (this.isSaving = false),
        error: () => (this.isSaving = false),
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
```

### 2. Create `document-review.component.html`

```html
<!-- document-review.component.html -->
<!-- Dual-pane document review layout (US-028 Scenario 1) -->
<!-- Accessible: both panes are keyboard-navigable; WCAG 2.1 AA labels applied -->
<div class="review-shell" *ngIf="vm; else loadingTpl" role="main">

  <!-- AI-Assisted label — always visible while status is PENDING_REVIEW -->
  <div class="ai-label-banner" role="status" aria-live="polite">
    <mat-icon aria-hidden="true">smart_toy</mat-icon>
    <span>AI-Assisted Draft — Review Required</span>
  </div>

  <div class="dual-pane-container">

    <!-- LEFT PANE: Read-only AI draft -->
    <section
      #leftPane
      class="pane pane--readonly"
      aria-label="AI-generated draft (read-only)"
      tabindex="0"
    >
      <header class="pane__header">
        <h2 class="pane__title">AI Draft</h2>
        <span class="pane__badge pane__badge--readonly" aria-label="Read only">Read-only</span>
      </header>
      <div
        class="pane__content"
        [innerHTML]="vm.aiDraftHtml"
        attr.contenteditable="false"
        attr.aria-readonly="true"
      ></div>
    </section>

    <!-- RIGHT PANE: Editable copy -->
    <section
      #rightPane
      class="pane pane--editable"
      aria-label="Editable document copy"
      tabindex="0"
    >
      <header class="pane__header">
        <h2 class="pane__title">Edit</h2>
        <span
          *ngIf="vm.status === 'PENDING_REVIEW'"
          class="pane__badge pane__badge--pending"
          aria-label="Pending review"
        >Pending Review</span>
      </header>

      <sh-document-editor
        [documentId]="documentId"
        [initialContent]="vm.content"
        [aiDraft]="vm.aiDraftContent"
        (saveDraft)="onSaveDraft($event)"
        [isSaving]="isSaving"
      />
    </section>

  </div>

  <!-- Change log timeline -->
  <sh-change-log-timeline [documentId]="documentId" />

</div>

<ng-template #loadingTpl>
  <div class="loading-container" role="status" aria-label="Loading document">
    <mat-progress-spinner mode="indeterminate" diameter="48" />
  </div>
</ng-template>
```

### 3. Create `document-review.component.scss`

```scss
// document-review.component.scss
// Dual-pane layout — flexbox side-by-side panes with independent scroll
:host {
  display: block;
  height: 100%;
}

.review-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 0;
}

.ai-label-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--sh-color-ai-label-bg, #fff3e0);
  color: var(--sh-color-ai-label-text, #e65100);
  font-size: 0.875rem;
  font-weight: 500;
  border-bottom: 1px solid var(--sh-color-ai-label-border, #ffe0b2);
}

.dual-pane-container {
  display: flex;
  flex: 1;
  overflow: hidden;
  gap: 1px;
  background: var(--sh-color-pane-divider, #e0e0e0);
}

.pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--sh-color-surface, #ffffff);

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--sh-color-border, #e0e0e0);
    background: var(--sh-color-surface-variant, #f5f5f5);
    position: sticky;
    top: 0;
    z-index: 1;
  }

  &__title {
    margin: 0;
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--sh-color-on-surface, #212121);
  }

  &__badge {
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 12px;

    &--readonly {
      background: var(--sh-color-readonly-bg, #eeeeee);
      color: var(--sh-color-readonly-text, #616161);
    }

    &--pending {
      background: var(--sh-color-warning-container, #fff8e1);
      color: var(--sh-color-warning, #f57f17);
    }
  }

  &__content {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    line-height: 1.6;
  }
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}
```

### 4. Create `frontend/src/app/features/documents/models/document-review.vm.ts`

```typescript
/** View model for DocumentReviewComponent — maps API Document to UI state. */
export interface DocumentReviewVm {
  id: string;
  status: 'DRAFT' | 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED';
  aiDraftHtml: string;        // Pre-sanitised HTML of the immutable AI draft
  aiDraftContent: Record<string, string>;  // Structured sections of AI draft
  content: Record<string, string>;         // Current editable content (may differ from draft)
  isAiAssisted: boolean;
  encounterId: string;
}
```

---

## File Locations

| File | Path |
|---|---|
| `document-review.component.ts` | `frontend/src/app/features/documents/document-review/document-review.component.ts` |
| `document-review.component.html` | `frontend/src/app/features/documents/document-review/document-review.component.html` |
| `document-review.component.scss` | `frontend/src/app/features/documents/document-review/document-review.component.scss` |
| `document-review.vm.ts` | `frontend/src/app/features/documents/models/document-review.vm.ts` |

---

## Validation Checklist

- [ ] Left pane renders with `contenteditable="false"` and `aria-readonly="true"`
- [ ] Right pane wraps `sh-document-editor` (TASK-006) — not a raw textarea
- [ ] Scroll sync mirrors `scrollTop` both ways (left→right and right→left)
- [ ] Scroll sync guard (`isScrollSyncing`) prevents infinite loop
- [ ] `AI-Assisted Draft` banner visible while `status === PENDING_REVIEW`
- [ ] `takeUntil(this.destroy$)` on all subscriptions — no memory leaks
- [ ] Component uses `ChangeDetectionStrategy.OnPush`
- [ ] WCAG 2.1 AA: both panes have `aria-label`, sections use `<section>` with `aria-label`
- [ ] Loading spinner shown while `vm` is null
- [ ] `isSaving` flag disables Save Draft button during in-flight request (TASK-006)

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-006` | `DocumentEditorComponent` (Quill editor with auto-save) |
| `TASK-007` | `ChangeLogTimelineComponent` |
| Angular Material 17 | `MatButtonModule`, `MatProgressSpinnerModule` |
