import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { MedicationReconciliation } from '../models/medication-row.model';

/**
 * HTTP client for medication reconciliation endpoints.
 * Source: US-030 Medication Reconciliation API.
 *
 * Base path: /api/v1/patients/{patientId}/medications
 */
@Injectable({ providedIn: 'root' })
export class MedicationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/patients`;

  /**
   * Retrieves the three-panel reconciliation payload for a patient.
   * GET /api/v1/patients/{patientId}/medications/reconciliation
   */
  getReconciliation(patientId: string): Observable<MedicationReconciliation> {
    return this.http.get<MedicationReconciliation>(
      `${this.base}/${patientId}/medications/reconciliation`
    );
  }
}
