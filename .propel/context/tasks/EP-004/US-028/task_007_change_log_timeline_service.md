---
id: TASK-007
title: "Implement Angular `ChangeLogTimelineComponent` and `DocumentService` API Client"
user_story: US-028
epic: EP-004
sprint: 2
layer: Frontend — Component & Service
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Frontend Engineer
upstream: [TASK-003, TASK-005, TASK-006]
---

# TASK-007: Implement Angular `ChangeLogTimelineComponent` and `DocumentService` API Client

> **Story:** US-028 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Frontend — Component & Service | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-028 DoD item 4 requires a **change log timeline** displayed below the editable pane showing:
author display name, UTC timestamp, and field changed — in chronological order.

This task also implements the `DocumentService` Angular service that wraps all three API calls:
`saveDraft`, `approveDocument`, and `rejectDocument`. The service is consumed by
`DocumentEditorComponent` (TASK-006) and `DocumentReviewComponent` (TASK-005).

---

## Acceptance Criteria Addressed

| US-028 AC | Requirement |
|---|---|
| **Scenario 2** | Change log timeline displays author, timestamp, field changed |
| **Scenario 3** | `DocumentService.saveDraft()` calls `PATCH /api/v1/documents/{id}` |
| **Scenario 4** | `DocumentService.approveDocument()` / `rejectDocument()` call the respective endpoints |

---

## Implementation Steps

### 1. Create `frontend/src/app/features/documents/services/document.service.ts`

```typescript
/**
 * DocumentService
 *
 * Angular service encapsulating all Document API calls for the review workflow.
 *
 * - saveDraft: PATCH /api/v1/documents/{id}
 * - approveDocument: PATCH /api/v1/documents/{id}/approve
 * - rejectDocument: PATCH /api/v1/documents/{id}/reject
 * - getChangeLog: GET /api/v1/documents/{id}/change-log
 * - getDocument: GET /api/v1/documents/{id}
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SaveDraftPayload } from '../document-editor/document-editor.component';
import { DocumentReviewVm } from '../models/document-review.vm';
import { ChangeLogEntry } from '../models/change-log-entry.model';

@Injectable({ providedIn: 'root' })
export class DocumentService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/documents`;

  /** Load document for dual-pane review. */
  getDocument(documentId: string): Observable<DocumentReviewVm> {
    return this.http.get<DocumentReviewVm>(`${this.base}/${documentId}`);
  }

  /**
   * Auto-save edited content and append change log entries.
   * Called by DocumentEditorComponent after 2-second debounce.
   */
  saveDraft(
    documentId: string,
    payload: SaveDraftPayload,
  ): Observable<{ document_id: string; status: string; changes_recorded: number }> {
    return this.http.patch<{ document_id: string; status: string; changes_recorded: number }>(
      `${this.base}/${documentId}`,
      payload,
    );
  }

  /**
   * Approve document — physician role only.
   * Backend returns 403 for non-physician callers.
   */
  approveDocument(
    documentId: string,
    body: { notes?: string },
  ): Observable<{ document_id: string; status: string }> {
    return this.http.patch<{ document_id: string; status: string }>(
      `${this.base}/${documentId}/approve`,
      body,
    );
  }

  /**
   * Reject document — all reviewer roles.
   * `rejection_reason` is mandatory (min 10 characters validated by backend).
   */
  rejectDocument(
    documentId: string,
    body: { rejection_reason: string },
  ): Observable<{ document_id: string; status: string }> {
    return this.http.patch<{ document_id: string; status: string }>(
      `${this.base}/${documentId}/reject`,
      body,
    );
  }

  /** Fetch paginated change log with author display names. */
  getChangeLog(documentId: string): Observable<ChangeLogEntry[]> {
    return this.http.get<ChangeLogEntry[]>(`${this.base}/${documentId}/change-log`);
  }
}
```

### 2. Create `frontend/src/app/features/documents/models/change-log-entry.model.ts`

```typescript
/** Client-side model for a single change log entry (mirrors ChangeLogEntryResponse). */
export interface ChangeLogEntry {
  field: string;
  old_value: unknown;
  new_value: unknown;
  author_id: string;
  timestamp: string;              // ISO 8601 UTC string
  author_display_name: string | null;
}
```

### 3. Create `change-log-timeline.component.ts`

```typescript
/**
 * ChangeLogTimelineComponent
 *
 * Displays the chronological change audit trail below the editable pane (US-028 DoD item 4).
 * Loads from GET /api/v1/documents/{id}/change-log on init and refreshes
 * whenever a new saveDraft completes (via SignalR or polling — Phase 2).
 */
import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnInit,
  inject,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { Observable } from 'rxjs';

import { DocumentService } from '../services/document.service';
import { ChangeLogEntry } from '../models/change-log-entry.model';

@Component({
  selector: 'sh-change-log-timeline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, DatePipe, MatExpansionModule, MatIconModule],
  templateUrl: './change-log-timeline.component.html',
  styleUrl: './change-log-timeline.component.scss',
})
export class ChangeLogTimelineComponent implements OnInit {
  @Input({ required: true }) documentId!: string;

  private readonly documentService = inject(DocumentService);

  changeLog$!: Observable<ChangeLogEntry[]>;

  ngOnInit(): void {
    this.changeLog$ = this.documentService.getChangeLog(this.documentId);
  }
}
```

### 4. Create `change-log-timeline.component.html`

```html
<!-- change-log-timeline.component.html -->
<section class="changelog" aria-label="Document change history">
  <h3 class="changelog__title">
    <mat-icon aria-hidden="true">history</mat-icon>
    Change History
  </h3>

  <ng-container *ngIf="changeLog$ | async as entries; else loadingTpl">
    <p *ngIf="entries.length === 0" class="changelog__empty" role="status">
      No changes recorded yet.
    </p>

    <ol class="changelog__list" aria-label="Change log entries">
      <li
        *ngFor="let entry of entries"
        class="changelog__entry"
        [attr.aria-label]="'Change to ' + entry.field + ' by ' + (entry.author_display_name ?? entry.author_id)"
      >
        <span class="changelog__dot" aria-hidden="true"></span>
        <div class="changelog__body">
          <span class="changelog__author">
            {{ entry.author_display_name ?? 'Unknown user' }}
          </span>
          <span class="changelog__meta">
            changed <strong>{{ entry.field | titlecase }}</strong>
            &bull;
            <time [dateTime]="entry.timestamp">
              {{ entry.timestamp | date: 'dd MMM yyyy, HH:mm' }} UTC
            </time>
          </span>
          <mat-expansion-panel class="changelog__diff-panel">
            <mat-expansion-panel-header>
              <mat-panel-title>View change</mat-panel-title>
            </mat-expansion-panel-header>
            <div class="changelog__diff">
              <div class="changelog__diff-old">
                <span class="label">Before</span>
                <pre>{{ entry.old_value | json }}</pre>
              </div>
              <div class="changelog__diff-new">
                <span class="label">After</span>
                <pre>{{ entry.new_value | json }}</pre>
              </div>
            </div>
          </mat-expansion-panel>
        </div>
      </li>
    </ol>
  </ng-container>

  <ng-template #loadingTpl>
    <p class="changelog__loading" role="status" aria-live="polite">Loading change history…</p>
  </ng-template>
</section>
```

### 5. Create `change-log-timeline.component.scss`

```scss
// change-log-timeline.component.scss
.changelog {
  padding: 16px;
  border-top: 1px solid var(--sh-color-border, #e0e0e0);

  &__title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 12px;
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--sh-color-on-surface, #212121);
  }

  &__list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  &__entry {
    display: flex;
    gap: 12px;
    padding: 8px 0;
    border-left: 2px solid var(--sh-color-primary, #1976d2);
    padding-left: 12px;
    margin-left: 4px;
  }

  &__dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--sh-color-primary, #1976d2);
    flex-shrink: 0;
    margin-top: 4px;
  }

  &__body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
  }

  &__author {
    font-weight: 500;
    font-size: 0.875rem;
    color: var(--sh-color-on-surface, #212121);
  }

  &__meta {
    font-size: 0.8125rem;
    color: var(--sh-color-on-surface-variant, #616161);
  }

  &__diff-panel {
    margin-top: 4px;
    box-shadow: none;
    border: 1px solid var(--sh-color-border, #e0e0e0);
    border-radius: 4px;
  }

  &__diff {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  &__diff-old,
  &__diff-new {
    .label {
      display: block;
      font-size: 0.75rem;
      font-weight: 600;
      margin-bottom: 4px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    pre {
      font-size: 0.8125rem;
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
    }
  }

  &__diff-old .label { color: var(--sh-color-error, #d32f2f); }
  &__diff-new .label { color: var(--sh-color-success, #388e3c); }

  &__empty,
  &__loading {
    font-size: 0.875rem;
    color: var(--sh-color-on-surface-variant, #616161);
    margin: 0;
  }
}
```

---

## File Locations

| File | Path |
|---|---|
| `document.service.ts` | `frontend/src/app/features/documents/services/document.service.ts` |
| `change-log-entry.model.ts` | `frontend/src/app/features/documents/models/change-log-entry.model.ts` |
| `change-log-timeline.component.ts` | `frontend/src/app/features/documents/change-log-timeline/change-log-timeline.component.ts` |
| `change-log-timeline.component.html` | `frontend/src/app/features/documents/change-log-timeline/change-log-timeline.component.html` |
| `change-log-timeline.component.scss` | `frontend/src/app/features/documents/change-log-timeline/change-log-timeline.component.scss` |

---

## Validation Checklist

- [ ] `DocumentService` is `providedIn: 'root'` — no additional provider registration needed
- [ ] `getDocument()`, `saveDraft()`, `approveDocument()`, `rejectDocument()`, `getChangeLog()` all typed with correct response interfaces
- [ ] `ChangeLogTimelineComponent` uses `async` pipe — no manual subscribe/unsubscribe
- [ ] Timeline renders author display name falling back to `author_id` if `null`
- [ ] Timestamp rendered with `DatePipe` in `'dd MMM yyyy, HH:mm'` UTC format
- [ ] Before/after diff values displayed via `mat-expansion-panel` (collapsed by default)
- [ ] "No changes recorded yet" message shown when change log is empty
- [ ] `ChangeDetectionStrategy.OnPush` applied to timeline component
- [ ] WCAG 2.1 AA: `<section aria-label>`, `<ol aria-label>`, each `<li>` has `aria-label`

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-003` | `GET /change-log` endpoint must exist |
| `TASK-006` | `SaveDraftPayload` interface imported into `DocumentService` |
| Angular Material 17 | `MatExpansionModule`, `MatIconModule` |
