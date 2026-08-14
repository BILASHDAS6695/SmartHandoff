import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { PendingDocument, DocumentActionPayload } from '../models/pending-document.model';

/**
 * Structured document content returned by the backend.
 */
export interface DocumentContent {
  diagnosis_summary?: Array<{
    icd10_code: string;
    description: string;
    is_primary?: boolean;
  }>;
  hospital_course?: string;
  medications_at_discharge?: Array<{
    drug_name: string;
    dose: string;
    frequency: string;
    route: string;
  }>;
  follow_up_instructions?: Array<{
    instruction: string;
    timeframe?: string;
  }>;
  warning_signs?: string[];
  activity_restrictions?: string[];
  generation_type?: 'AI' | 'TEMPLATE';
}

/**
 * Full document resource returned by the backend.
 */
export interface BackendDocument {
  id: string;
  encounter_id: string;
  document_type: string;
  content: DocumentContent | Record<string, any> | string;
  language_code: string;
  status: string;
  generation_type: string;
  ai_assisted_label: boolean;
  approved_at: string | null;
  reviewed_by_user_id: string | null;
  reviewed_by_display_name: string | null;
  created_at: string;
  updated_at: string;
}

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
  private readonly encountersBase = `${environment.apiBaseUrl}/api/v1/encounters`;

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

  /**
   * Lists all documents for a specific encounter.
   * GET /api/v1/encounters/{encounterId}/documents
   */
  getDocumentsByEncounter(encounterId: string): Observable<BackendDocument[]> {
    return this.http.get<BackendDocument[]>(
      `${this.encountersBase}/${encounterId}/documents`
    );
  }

  /**
   * Fetches a single document by ID.
   * GET /api/v1/documents/{documentId}
   */
  getDocument(documentId: string): Observable<BackendDocument> {
    return this.http.get<BackendDocument>(`${this.base}/${documentId}`);
  }

  /**
   * Generates a role-based clinical document for an encounter.
   * POST /api/v1/encounters/{encounterId}/documents/generate
   */
  generateDocument(
    encounterId: string,
    agentRole: string,
    regenerate = false
  ): Observable<BackendDocument> {
    return this.http.post<BackendDocument>(
      `${this.encountersBase}/${encounterId}/documents/generate`,
      { agent_role: agentRole, regenerate }
    );
  }
}
