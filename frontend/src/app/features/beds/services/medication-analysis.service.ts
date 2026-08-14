import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@environments/environment';

export interface MedicationAnalysisResult {
  encounter_id: string;
  summary: string;
  readmission_risk: string;
  confidence: string;
  safety_score: number;
  risks: string[];
  recommendations: string[];
  predicted_issues: string[];
}

/**
 * MedicationAnalysisService — calls the AI medication-analysis endpoint.
 */
@Injectable({ providedIn: 'root' })
export class MedicationAnalysisService {
  private readonly http = inject(HttpClient);
  private readonly apiBase = `${environment.apiBaseUrl}/api/v1/encounters`;

  /**
   * Analyses medications for an encounter and predicts readmission risk.
   * @param encounterId Encounter UUID.
   */
  analyzeEncounter(encounterId: string): Observable<MedicationAnalysisResult> {
    return this.http.get<MedicationAnalysisResult>(
      `${this.apiBase}/${encodeURIComponent(encounterId)}/medications/analysis`
    );
  }
}
