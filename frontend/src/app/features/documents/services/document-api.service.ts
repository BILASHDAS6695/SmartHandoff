import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { PendingDocument, DocumentActionPayload } from '../models/pending-document.model';

/**
 * HTTP client for document approval queue endpoints.
 * Source: US-025 Document API.
 *
 * Base path: /api/v1/documents
 */
@Injectable({ providedIn: 'root' })
export class DocumentApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/documents`;

  /**
   * Returns all PENDING_REVIEW documents assigned to the current physician.
   * GET /api/v1/documents?status=PENDING_REVIEW&assignedTo=me
   */
  getPendingReviewQueue(): Observable<PendingDocument[]> {
    const params = new HttpParams()
      .set('status', 'PENDING_REVIEW')
      .set('assignedTo', 'me');
    return this.http.get<PendingDocument[]>(this.base, { params });
  }

  /**
   * Approves or rejects a document.
   * PATCH /api/v1/documents/{documentId}/review
   */
  reviewDocument(
    documentId: string,
    payload: DocumentActionPayload
  ): Observable<PendingDocument> {
    return this.http.patch<PendingDocument>(
      `${this.base}/${documentId}/review`,
      payload
    );
  }
}
