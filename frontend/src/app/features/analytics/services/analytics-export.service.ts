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
  poll_url?: string;
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
        switchMap((job) => this._pollUntilComplete(job.poll_url ?? '')),
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
