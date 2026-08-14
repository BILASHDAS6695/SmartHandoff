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
  reconciliation_completed_by: string | null;
  medications: MedicationReconciliationResult[];
}

/** Backend medication list response shape. */
export interface MedicationListResponse {
  medications: MedicationReconciliationResult[];
  total: number;
  user: string;
}

/** Per-encounter medication history snapshot. */
export interface MedicationHistoryEncounter {
  encounter_id: string;
  status: string;
  created_at: string | null;
  total_medications: number;
  medications: MedicationReconciliationResult[];
}

/** Backend medication history response shape. */
export interface MedicationHistoryResponse {
  current_encounter_id: string;
  patient_id: string;
  history: MedicationHistoryEncounter[];
}

/** Backend pharmacist alert shape. */
export interface PharmacistAlert {
  id: string;
  encounter_id: string;
  alert_type: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  status: 'ACTIVE' | 'RESOLVED';
  drug_class: string | null;
  drug_name: string | null;
  drug_pair: string[] | null;
  interaction_description: string | null;
  source: string;
  sla_breached: boolean;
  resolved_by_user_id: string | null;
  resolved_at: string | null;
  resolution_type: string | null;
  created_at: string;
}

/** Payload for resolving a pharmacist alert. */
export interface AlertResolveRequest {
  resolution_type: 'REVIEWED_ACCEPTABLE' | 'DOSE_ADJUSTED' | 'DRUG_CHANGED' | 'DISCONTINUED';
  resolution_note?: string | null;
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
  private readonly medicationsBase = `${environment.apiBaseUrl}/api/v1/medications`;
  private readonly alertsBase = `${environment.apiBaseUrl}/api/v1/alerts`;

  /**
   * Retrieves the medication reconciliation results for an encounter.
   * GET /api/v1/encounters/{encounterId}/medications/reconciliation
   */
  getReconciliation(encounterId: string): Observable<MedicationReconciliationResponse> {
    return this.http.get<MedicationReconciliationResponse>(
      `${this.base}/${encounterId}/medications/reconciliation`
    );
  }

  /**
   * Retrieves all medications across encounters.
   * GET /api/v1/medications
   */
  getAllMedications(): Observable<MedicationListResponse> {
    return this.http.get<MedicationListResponse>(this.medicationsBase);
  }

  /**
   * Generates or retrieves medication reconciliation for an encounter.
   * POST /api/v1/encounters/{encounterId}/medications/reconciliation
   */
  generateReconciliation(encounterId: string): Observable<MedicationReconciliationResponse> {
    return this.http.post<MedicationReconciliationResponse>(
      `${this.base}/${encounterId}/medications/reconciliation`,
      {}
    );
  }

  /**
   * Marks medication reconciliation as complete for an encounter.
   * POST /api/v1/encounters/{encounterId}/medications/reconciliation/complete
   */
  completeReconciliation(encounterId: string): Observable<MedicationReconciliationResponse> {
    return this.http.post<MedicationReconciliationResponse>(
      `${this.base}/${encounterId}/medications/reconciliation/complete`,
      {}
    );
  }

  /**
   * Retrieves pharmacist alerts for an encounter.
   * GET /api/v1/alerts/encounters/{encounterId}/alerts
   */
  getEncounterAlerts(encounterId: string): Observable<PharmacistAlert[]> {
    return this.http.get<PharmacistAlert[]>(
      `${this.alertsBase}/encounters/${encounterId}/alerts`
    );
  }

  /**
   * Resolves a pharmacist alert.
   * PATCH /api/v1/alerts/{alertId}/resolve
   */
  resolveAlert(alertId: string, payload: AlertResolveRequest): Observable<PharmacistAlert> {
    return this.http.patch<PharmacistAlert>(
      `${this.alertsBase}/${alertId}/resolve`,
      payload
    );
  }

  /**
   * Retrieves medication reconciliation results for the patient's prior encounters.
   * GET /api/v1/encounters/{encounterId}/medications/history
   */
  getMedicationHistory(encounterId: string): Observable<MedicationHistoryResponse> {
    return this.http.get<MedicationHistoryResponse>(
      `${this.base}/${encounterId}/medications/history`
    );
  }
}
