---
id: TASK-005
title: "Angular Export Buttons — CSV & PDF Download Controls on Analytics Dashboard"
user_story: US-063
epic: EP-012
sprint: 2
layer: Frontend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-063/TASK-001, US-061/TASK-003, US-061/TASK-004]
---

# TASK-005: Angular Export Buttons — CSV & PDF Download Controls on Analytics Dashboard

> **Story:** US-063 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Frontend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-063 AC Scenario 2 states the manager clicks "Export PDF" on the analytics dashboard. This task adds both "Export CSV" and "Export PDF" action buttons to the Angular `AnalyticsDashboardComponent` (scaffolded in US-061/TASK-003), wires them to the backend `GET /api/v1/analytics/export` endpoint, and handles the two response modes:

- **CSV**: direct `200 OK` `Blob` download triggered via `<a>` element programmatic click
- **PDF**: `202 Accepted` polling flow — show progress spinner; poll `/api/v1/analytics/export/status/{job_id}` until a `download_url` is available; then trigger browser download

The export service, `AnalyticsExportService`, encapsulates all HTTP calls and polling logic to keep the component thin (Single Responsibility Principle).

**Design references:**
- design.md §3.4 — Angular feature module structure `features/analytics/`
- design.md §4.1 — Angular 17; `HttpClient`; reactive forms for date filter integration
- US-063 AC Scenario 2 — manager clicks "Export PDF" on analytics dashboard
- US-063 AC Scenario 4 — export buttons hidden for non-manager roles (RBAC guard on route)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | "Export CSV" button triggers file download with correct filename |
| Scenario 2 | "Export PDF" button shows spinner, polls for completion, triggers PDF download |
| Scenario 4 | Export buttons rendered only when `currentUser.role` is `MANAGER` or `ADMIN` |

---

## Implementation Steps

### 1. Create export service

```bash
touch smarthandoff-angular/src/app/features/analytics/services/analytics-export.service.ts
```

```typescript
/**
 * AnalyticsExportService
 *
 * Handles CSV and PDF export HTTP calls for the analytics dashboard.
 *
 * CSV:  GET /api/v1/analytics/export?format=csv  → 200 Blob → trigger download
 * PDF:  GET /api/v1/analytics/export?format=pdf  → 202 { job_id, poll_url }
 *       → poll poll_url every 3 s until status=complete → trigger download
 *
 * Design refs:
 *   design.md §3.4 — Angular feature module service pattern
 *   US-063 AC Scenario 1 — CSV download within 5 s
 *   US-063 AC Scenario 2 — PDF 202 + polling
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import {
  Observable,
  interval,
  switchMap,
  filter,
  take,
  timeout,
  throwError,
} from 'rxjs';
import { environment } from '../../../../environments/environment';

export interface ExportJobStatus {
  job_id: string;
  status: 'processing' | 'complete' | 'error';
  download_url?: string;
}

@Injectable({ providedIn: 'root' })
export class AnalyticsExportService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/analytics/export`;

  /** Download CSV immediately as a Blob and trigger browser save-as dialog. */
  downloadCsv(fromDate: string, toDate: string): Observable<void> {
    const params = new HttpParams()
      .set('format', 'csv')
      .set('from', fromDate)
      .set('to', toDate);

    return new Observable((observer) => {
      this.http
        .get(this.baseUrl, { params, responseType: 'blob', observe: 'response' })
        .subscribe({
          next: (response) => {
            const filename =
              this._extractFilename(response.headers.get('content-disposition')) ??
              `kpi_report_${fromDate}_${toDate}.csv`;
            this._triggerBlobDownload(response.body!, filename);
            observer.next();
            observer.complete();
          },
          error: (err) => observer.error(err),
        });
    });
  }

  /**
   * Initiate PDF export (202 Accepted) and poll until the download URL is ready.
   * Emits the download URL string once available; times out after 120 seconds.
   */
  initiatePdfExport(fromDate: string, toDate: string): Observable<string> {
    const params = new HttpParams()
      .set('format', 'pdf')
      .set('from', fromDate)
      .set('to', toDate);

    return this.http
      .get<ExportJobStatus>(this.baseUrl, { params })
      .pipe(
        switchMap((job) => this._pollUntilComplete(job.poll_url)),
        timeout({
          each: 120_000,
          with: () => throwError(() => new Error('PDF export timed out after 120 seconds.')),
        }),
      );
  }

  private _pollUntilComplete(pollUrl: string): Observable<string> {
    return interval(3_000).pipe(
      switchMap(() =>
        this.http.get<ExportJobStatus>(`${environment.apiBaseUrl}${pollUrl}`)
      ),
      filter((status) => status.status === 'complete' && !!status.download_url),
      take(1),
      switchMap((status) => {
        this._triggerUrlDownload(status.download_url!);
        return [status.download_url!];
      }),
    );
  }

  private _extractFilename(contentDisposition: string | null): string | null {
    if (!contentDisposition) return null;
    const match = /filename=([^\s;]+)/.exec(contentDisposition);
    return match?.[1] ?? null;
  }

  private _triggerBlobDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    this._triggerUrlDownload(url, filename);
    URL.revokeObjectURL(url);
  }

  private _triggerUrlDownload(url: string, filename?: string): void {
    const anchor = document.createElement('a');
    anchor.href = url;
    if (filename) anchor.download = filename;
    anchor.click();
  }
}
```

### 2. Update `AnalyticsDashboardComponent` — add export action buttons

```bash
# File already exists from US-061/TASK-003
# Edit: smarthandoff-angular/src/app/features/analytics/analytics-dashboard.component.ts
```

```typescript
// Add to component class in analytics-dashboard.component.ts

import { AnalyticsExportService } from './services/analytics-export.service';

// Inject in constructor / via inject()
private readonly exportService = inject(AnalyticsExportService);

isExportingCsv = false;
isExportingPdf = false;
exportError: string | null = null;

onExportCsv(): void {
  this.isExportingCsv = true;
  this.exportError = null;
  this.exportService
    .downloadCsv(this.filterForm.value.from, this.filterForm.value.to)
    .subscribe({
      next: () => (this.isExportingCsv = false),
      error: (err) => {
        this.isExportingCsv = false;
        this.exportError = 'CSV export failed. Please try again.';
        console.error('[AnalyticsDashboard] CSV export error:', err);
      },
    });
}

onExportPdf(): void {
  this.isExportingPdf = true;
  this.exportError = null;
  this.exportService
    .initiatePdfExport(this.filterForm.value.from, this.filterForm.value.to)
    .subscribe({
      next: () => (this.isExportingPdf = false),
      error: (err) => {
        this.isExportingPdf = false;
        this.exportError = 'PDF export failed or timed out. Please try again.';
        console.error('[AnalyticsDashboard] PDF export error:', err);
      },
    });
}
```

### 3. Update `analytics-dashboard.component.html` — add export buttons

```html
<!-- Add inside the analytics dashboard header/toolbar area -->
<!-- Visible only to MANAGER and ADMIN roles -->
@if (currentUser.role === 'MANAGER' || currentUser.role === 'ADMIN') {
  <div class="export-actions" aria-label="Export KPI report">
    <button
      mat-stroked-button
      color="primary"
      [disabled]="isExportingCsv"
      (click)="onExportCsv()"
      aria-label="Export KPI data as CSV file"
    >
      @if (isExportingCsv) {
        <mat-spinner diameter="18" aria-hidden="true" />
      } @else {
        <mat-icon aria-hidden="true">download</mat-icon>
      }
      Export CSV
    </button>

    <button
      mat-flat-button
      color="primary"
      [disabled]="isExportingPdf"
      (click)="onExportPdf()"
      aria-label="Export KPI report as PDF document"
    >
      @if (isExportingPdf) {
        <mat-spinner diameter="18" aria-hidden="true" />
        Generating PDF…
      } @else {
        <mat-icon aria-hidden="true">picture_as_pdf</mat-icon>
        Export PDF
      }
    </button>

    @if (exportError) {
      <mat-error role="alert" aria-live="assertive">{{ exportError }}</mat-error>
    }
  </div>
}
```

### 4. Add export action styles to `analytics-dashboard.component.scss`

```scss
.export-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;

  mat-spinner {
    display: inline-block;
    margin-right: 6px;
    vertical-align: middle;
  }

  mat-error {
    font-size: 12px;
    width: 100%;
    margin-top: 4px;
  }
}
```

---

## Validation Checklist

- [ ] "Export CSV" button visible in the analytics dashboard for `MANAGER` role
- [ ] "Export CSV" button hidden for `NURSE` role (role guard on component template)
- [ ] Clicking "Export CSV" triggers a `GET /api/v1/analytics/export?format=csv&…` request
- [ ] CSV file downloads automatically with filename `kpi_report_{from}_{to}.csv`
- [ ] Spinner shown on "Export CSV" button while download is in progress
- [ ] Clicking "Export PDF" triggers a `GET /api/v1/analytics/export?format=pdf&…` request
- [ ] Spinner and "Generating PDF…" text shown during the 202 polling phase
- [ ] PDF file downloads automatically once the signed URL becomes available
- [ ] Error message appears below the buttons if the export fails or times out
- [ ] Both buttons are keyboard-accessible and have `aria-label` attributes (WCAG 2.1 AA)
- [ ] `AnalyticsExportService` has no direct DOM manipulation outside `_triggerBlobDownload`
