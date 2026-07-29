import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { PatientListQuery, PatientListResponse } from '../models/patient.model';

/**
 * HTTP client for the patient list API endpoint.
 *
 * RBAC note: the `unit` parameter is always set by the caller (PatientListComponent)
 * reading from the decoded JWT claim. The server re-enforces this filter independently
 * (FR-074). This service does NOT perform client-side filtering.
 */
@Injectable({ providedIn: 'root' })
export class PatientApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/patients`;

  /**
   * Fetches paginated patient list for the specified unit.
   * @param query - Unit, optional search term, page, and page_size
   */
  getPatients(query: PatientListQuery): Observable<PatientListResponse> {
    let params = new HttpParams()
      .set('unit', query.unit)
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.page_size ?? 25));

    if (query.search?.trim()) {
      params = params.set('search', query.search.trim());
    }

    return this.http.get<PatientListResponse>(this.baseUrl, { params });
  }
}
