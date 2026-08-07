import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { MedicationReconciliation, MedicationRow } from '../models/medication-row.model';

/**
 * Raw medication record as returned by the backend reconciliation endpoint.
 */
interface BackendMedication {
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

interface BackendReconciliationResponse {
  encounter_id: string;
  total_medications: number;
  reconciliation_completed_at: string | null;
  medications: BackendMedication[];
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
   * Retrieves the three-panel reconciliation payload for an encounter.
   * GET /api/v1/encounters/{encounterId}/medications/reconciliation
   */
  getReconciliation(encounterId: string): Observable<MedicationReconciliation> {
    return this.http
      .get<BackendReconciliationResponse>(
        `${this.base}/${encounterId}/medications/reconciliation`
      )
      .pipe(map((response) => this.toViewModel(response)));
  }

  private toViewModel(response: BackendReconciliationResponse): MedicationReconciliation {
    const medications = response.medications ?? [];

    const toRow = (med: BackendMedication): MedicationRow => ({
      id: med.id,
      drugName: med.name,
      dose: med.dose ?? '',
      frequency: med.frequency ?? '',
      interactionSeverity: med.interaction_severity ?? null,
      alertId: med.flags?.length ? med.flags[0] : null,
    });

    return {
      encounterId: response.encounter_id,
      preAdmit: medications.filter((m) => m.pre_admit).map(toRow),
      inpatient: medications.filter((m) => m.inpatient).map(toRow),
      discharge: medications.filter((m) => m.discharge).map(toRow),
    };
  }
}
