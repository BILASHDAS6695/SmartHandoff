---
id: TASK-004
title: "Implement `DocumentQueueComponent` — Physician Approval Queue with Approve/Reject Actions"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Feature Component
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-074, UI-008, US-025]
---

# TASK-004: Implement `DocumentQueueComponent` — Physician Approval Queue with Approve/Reject Actions

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Feature Component | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

Physician Dr. David lands on `/dashboard` and expects an "Awaiting Approval" panel listing all `PENDING_REVIEW` AI-generated documents assigned to his patients. Each list item shows the document type, patient name, generation timestamp, and a content excerpt. Quick-action buttons (Approve / Reject) let him act without navigating away. The sidebar nav item also carries a `MatBadge` count that reflects the current queue size, updated in real time via the `document_created` SignalR event (wired in TASK-006).

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **Scenario 3** | "Awaiting Approval" panel on `/dashboard` for physician role; all PENDING_REVIEW documents listed; count badge in sidebar reflects queue size |

---

## Implementation Steps

### 1. Create `DocumentQueueComponent` in `features/documents/components/document-queue/`

**`document-queue.component.ts`**

```typescript
import {
  Component, OnInit, ChangeDetectionStrategy, signal, inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatListModule } from '@angular/material/list';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDividerModule } from '@angular/material/divider';
import { DocumentApiService } from '../../services/document-api.service';
import { PendingDocument } from '../../models/pending-document.model';
import { DocumentQueueStore } from '../../store/document-queue.store';

/**
 * Displays the physician's document approval queue on the dashboard.
 * Lists PENDING_REVIEW AI-generated documents with approve/reject actions.
 *
 * Intended placement: dashboard home panel (physician role only).
 * Queue count is also exposed via DocumentQueueStore for sidebar badge.
 */
@Component({
  selector: 'app-document-queue',
  standalone: true,
  imports: [
    CommonModule,
    MatListModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatDividerModule,
  ],
  templateUrl: './document-queue.component.html',
  styleUrls: ['./document-queue.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DocumentQueueComponent implements OnInit {
  private readonly documentApi = inject(DocumentApiService);
  private readonly queueStore = inject(DocumentQueueStore);

  documents = signal<PendingDocument[]>([]);
  isLoading = signal(true);
  hasError = signal(false);
  /** Track which documentId is being actioned to show per-item spinner */
  pendingActionId = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading.set(true);
    this.hasError.set(false);
    this.documentApi.getPendingReviewQueue().subscribe({
      next: (docs) => {
        this.documents.set(docs);
        this.queueStore.setCount(docs.length);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  approve(doc: PendingDocument): void {
    this.pendingActionId.set(doc.documentId);
    this.documentApi
      .reviewDocument(doc.documentId, { action: 'APPROVED' })
      .subscribe({
        next: () => this.removeDocument(doc.documentId),
        error: () => this.pendingActionId.set(null),
      });
  }

  reject(doc: PendingDocument): void {
    this.pendingActionId.set(doc.documentId);
    // Rejection reason collection can be extended via a prompt dialog in a later sprint
    this.documentApi
      .reviewDocument(doc.documentId, { action: 'REJECTED' })
      .subscribe({
        next: () => this.removeDocument(doc.documentId),
        error: () => this.pendingActionId.set(null),
      });
  }

  private removeDocument(documentId: string): void {
    this.documents.update((docs) => docs.filter((d) => d.documentId !== documentId));
    this.queueStore.setCount(this.documents().length);
    this.pendingActionId.set(null);
  }
}
```

**`document-queue.component.html`**

```html
<section class="doc-queue" aria-labelledby="doc-queue-heading">

  <header class="doc-queue__header">
    <h2 id="doc-queue-heading" class="doc-queue__title">
      Awaiting Approval
      <span class="doc-queue__count" aria-live="polite">
        ({{ documents().length }})
      </span>
    </h2>
  </header>

  <!-- Loading -->
  <div *ngIf="isLoading()" class="doc-queue__loading" aria-busy="true" aria-label="Loading approval queue">
    <mat-spinner diameter="32"></mat-spinner>
  </div>

  <!-- Error state -->
  <div *ngIf="hasError() && !isLoading()" role="alert" class="doc-queue__error">
    <mat-icon aria-hidden="true">error_outline</mat-icon>
    <span>Failed to load approval queue.</span>
    <button mat-stroked-button color="warn" (click)="load()">Retry</button>
  </div>

  <!-- Empty state -->
  <div *ngIf="!isLoading() && !hasError() && documents().length === 0" class="doc-queue__empty">
    <mat-icon aria-hidden="true">check_circle_outline</mat-icon>
    <span>No documents awaiting approval.</span>
  </div>

  <!-- Document list -->
  <mat-list *ngIf="!isLoading() && !hasError() && documents().length > 0" role="list">
    <ng-container *ngFor="let doc of documents(); trackBy: trackById">
      <mat-list-item class="doc-queue__item" role="listitem">
        <div class="doc-queue__item-content">
          <div class="doc-queue__item-meta">
            <span class="doc-queue__patient-name">{{ doc.patientName }}</span>
            <mat-chip class="doc-queue__type-chip" [attr.aria-label]="'Document type: ' + doc.documentType">
              {{ doc.documentType | titlecase }}
            </mat-chip>
            <span class="doc-queue__date" [attr.aria-label]="'Generated at ' + (doc.generatedAt | date:'medium')">
              {{ doc.generatedAt | date:'dd MMM, HH:mm' }}
            </span>
          </div>
          <p class="doc-queue__excerpt" aria-label="Document excerpt">
            {{ doc.contentExcerpt }}
          </p>
          <div class="doc-queue__actions">
            <button
              mat-stroked-button
              color="primary"
              (click)="approve(doc)"
              [disabled]="pendingActionId() !== null"
              [attr.aria-label]="'Approve document for ' + doc.patientName"
            >
              <mat-spinner *ngIf="pendingActionId() === doc.documentId" diameter="16"></mat-spinner>
              <mat-icon *ngIf="pendingActionId() !== doc.documentId" aria-hidden="true">check</mat-icon>
              Approve
            </button>
            <button
              mat-stroked-button
              color="warn"
              (click)="reject(doc)"
              [disabled]="pendingActionId() !== null"
              [attr.aria-label]="'Reject document for ' + doc.patientName"
            >
              <mat-icon aria-hidden="true">close</mat-icon>
              Reject
            </button>
          </div>
        </div>
      </mat-list-item>
      <mat-divider></mat-divider>
    </ng-container>
  </mat-list>

</section>
```

**`document-queue.component.scss`**

```scss
.doc-queue {
  background: var(--mat-sys-surface);
  border-radius: 8px;
  border: 1px solid var(--mat-divider-color);
  overflow: hidden;

  &__header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--mat-divider-color);
  }

  &__title {
    font-size: 16px;
    font-weight: 600;
    margin: 0;
  }

  &__count {
    font-size: 14px;
    font-weight: 400;
    color: var(--mat-sys-outline);
    margin-left: 4px;
  }

  &__loading,
  &__empty,
  &__error {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 24px 20px;
    color: var(--mat-sys-outline);
  }

  &__item {
    height: auto !important;
    padding: 12px 0 !important;
  }

  &__item-content {
    width: 100%;
    padding: 0 20px;
  }

  &__item-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 6px;
  }

  &__patient-name {
    font-weight: 600;
    font-size: 14px;
  }

  &__type-chip {
    font-size: 11px !important;
    height: 20px !important;
  }

  &__date {
    font-size: 12px;
    color: var(--mat-sys-outline);
    margin-left: auto;
  }

  &__excerpt {
    font-size: 13px;
    color: var(--mat-sys-on-surface-variant);
    margin: 0 0 10px;
    line-height: 1.4;
  }

  &__actions {
    display: flex;
    gap: 8px;
  }
}
```

### 2. Create `DocumentQueueStore` Signal Store in `features/documents/store/`

This lightweight store exposes the queue count to the sidebar badge (TASK-006) without coupling the queue component to the shell.

**`document-queue.store.ts`**

```typescript
import { Injectable, signal } from '@angular/core';

/**
 * Lightweight signal store for document queue count.
 * Consumed by:
 *  - DocumentQueueComponent (writes count on load/action)
 *  - DashboardShellComponent sidebar nav (reads count for MatBadge)
 *  - SignalR handler for document_created event (increments count)
 */
@Injectable({ providedIn: 'root' })
export class DocumentQueueStore {
  private readonly _count = signal(0);

  /** Current pending review document count — used by sidebar MatBadge */
  readonly count = this._count.asReadonly();

  setCount(count: number): void {
    this._count.set(count);
  }

  increment(): void {
    this._count.update((n) => n + 1);
  }

  decrement(): void {
    this._count.update((n) => Math.max(0, n - 1));
  }
}
```

### 3. Add `DocumentQueueComponent` to Dashboard Home (Physician Role)

In `features/dashboard/components/dashboard-home/dashboard-home.component.html` (extends US-047 scaffold):

```html
<!-- Physician-only approval queue panel -->
<app-document-queue
  *ngIf="currentUser()?.roles?.includes('physician')"
  class="dashboard-home__queue-panel"
  aria-label="Document approval queue"
/>
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| CREATE | `src/app/features/documents/components/document-queue/document-queue.component.ts` |
| CREATE | `src/app/features/documents/components/document-queue/document-queue.component.html` |
| CREATE | `src/app/features/documents/components/document-queue/document-queue.component.scss` |
| CREATE | `src/app/features/documents/store/document-queue.store.ts` |
| MODIFY | `src/app/features/dashboard/components/dashboard-home/dashboard-home.component.html` — add `<app-document-queue>` conditional block |

---

## Validation Checklist

- [ ] Component renders only when current user has `physician` role
- [ ] All `PENDING_REVIEW` documents from API displayed in `MatList`
- [ ] Patient name, document type (chip), generation date, and excerpt all visible per item
- [ ] Approve action removes item from list; `DocumentQueueStore.count` decrements
- [ ] Reject action removes item from list; `DocumentQueueStore.count` decrements
- [ ] Per-item spinner shown during in-flight action; other action buttons disabled
- [ ] Empty state panel renders when queue is empty
- [ ] Error state with Retry button renders on API failure
- [ ] `DocumentQueueStore.count` emits correct value on initial load

---

## Dependencies

| Dependency | Notes |
|---|---|
| TASK-002 (this story) | `DocumentApiService` required |
| US-025 | Document API operational |
| US-047 | Dashboard shell layout and `currentUser()` signal available |
