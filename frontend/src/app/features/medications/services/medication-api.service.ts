import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';

/** Backend medication reconciliation row (US-030). */
export interface MedicationReconciliationResult {
  id: string;
  name: string;
  rxnorm_cui: string | null;
  reconciliation_category: string | null;
  pre_admit: boolean;
  inpatient: boolean;
  discharge: boolean;
  flags: string[];
  dose: string | null;
  route: string | null;
  frequency: string | null;
  interaction_severity: 'HIGH' | 'MEDIUM' | 'LOW' | null;
}

/** Backend medication reconciliation response shape. */
export interface MedicationReconciliationResponse {
  encounter_id: string;
  total_medications: number;
  reconciliation_completed_at: string | null;
  medications: MedicationReconciliationResult[];
}

/**
 * HTTP client for medication reconciliation endpoints.
 * Source: US-030 Medication Reconciliation API.
 *
 * Base path: /api/v1/encounters/{encounterId}/medications
 */
@Injectable({ providedIn: 'root' })
export class MedicationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/encounters`;

  /**
   * Retrieves the medication reconciliation results for an encounter.
   * GET /api/v1/encounters/{encounterId}/medications/reconciliation
   */
  getReconciliation(encounterId: string): Observable<MedicationReconciliationResponse> {
    return this.http.get<MedicationReconciliationResponse>(
      `${this.base}/${encounterId}/medications/reconciliation`
    );
  }
}
