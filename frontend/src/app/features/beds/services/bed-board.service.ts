import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { BedDetailDto, BedDto, BedItem, BedStatus, BedSuggestion } from '../models/bed.model';
import { environment } from '@environments/environment';

/** Raw mv_bed_board row shape returned by GET /api/v1/beds (snake_case). */
interface RawBedItem {
  bed_id: string;
  unit: string;
  room: string;
  bed_number: string;
  bed_type: string;
  status: BedStatus;
  isolation_required: boolean;
  gender_designation: string;
  encounter_id: string | null;
  last_updated?: string;
  predicted_discharge_time: string | null;
  discharge_prediction_confidence: 'high' | 'medium' | 'low' | null;
  discharge_prediction_interval_hours: number | null;
}

/**
 * BedBoardService — HTTP service for fetching bed board data.
 * Wraps GET /api/v1/beds endpoint returning materialised view (mv_bed_board) with predictions.
 * Maps BedItem API responses to BedDto for UI consumption.
 * Used by BedBoardComponent (US-050 TASK-001).
 */
@Injectable({ providedIn: 'root' })
export class BedBoardService {
  private readonly http = inject(HttpClient);
  private readonly apiBase = `${environment.apiBaseUrl}/api/v1/beds`;

  /**
   * Fetches current bed inventory with optional discharge predictions.
   * Automatically transforms BedItem API response to BedDto for UI rendering.
   * @param includePredictions When true, includes predicted_discharge_time from mv_bed_board.
   * @returns Observable<BedDto[]> Array of bed objects mapped for colour-coding and display.
   */
  getBeds(includePredictions = true): Observable<BedDto[]> {
    const params = new HttpParams().set('include_predictions', String(includePredictions));
    return this.http.get<RawBedItem[]>(this.apiBase, { params }).pipe(
      map(items => items.map(item => this.mapBedItemToDto(item)))
    );
  }

  /**
   * Fetches detailed information for a single bed, including the current
   * occupant (when occupied) and patients waiting for bed allocation.
   * @param bedId Bed UUID or human-readable bed_number.
   */
  getBedDetails(bedId: string): Observable<BedDetailDto> {
    return this.http.get<BedDetailDto>(`${this.apiBase}/${encodeURIComponent(bedId)}/details`);
  }

  /**
   * Fetches pending bed-management suggestions with ranked beds.
   * @returns Observable of pending bed suggestions for the bed manager.
   */
  getSuggestions(): Observable<BedSuggestion[]> {
    return this.http.get<BedSuggestion[]>(`${this.apiBase}/suggestions`);
  }

  /**
   * Approves a bed suggestion and assigns the selected bed.
   * @param taskId Bed management AgentTask id.
   * @param payload Assignment details including bed_id and reason.
   */
  assignSuggestion(
    taskId: string,
    payload: {
      bed_id: string;
      reason: string;
      isolation_confirmed?: boolean;
      notes?: string;
    }
  ): Observable<{ task_id: string; encounter_id: string; bed_id: string; bed_number: string; unit: string; status: BedStatus; previous_status: BedStatus }> {
    return this.http.post<any>(`${this.apiBase}/suggestions/${taskId}/assign`, payload);
  }

  /**
   * Declines a bed suggestion.
   * @param taskId Bed management AgentTask id.
   * @param reason Reason for declining.
   */
  declineSuggestion(taskId: string, reason: string): Observable<{ task_id: string; encounter_id: string; status: string }> {
    return this.http.post<any>(`${this.apiBase}/suggestions/${taskId}/decline`, { reason });
  }

  /**
   * Transforms a BedItem (from API) to BedDto (for UI).
   * Extracts essential fields and calculates derived data like risk tier.
   * @param item BedItem from API response
   * @returns BedDto suitable for bed board UI rendering
   */
  private mapBedItemToDto(item: RawBedItem): BedDto {
    return {
      bedId: item.bed_number || item.bed_id,
      unit: item.unit,
      status: item.status,
      patientName: null, // Patient name sourced from separate Patient API (privacy boundary)
      predictedDischargeTime: item.predicted_discharge_time,
      assignedNurse: null, // Assigned nurse sourced from Nurse assignment API
      riskTier: this.calculateRiskTier(item), // Derive from confidence level (US-036)
    };
  }

  /**
   * Calculates patient risk tier based on discharge prediction confidence.
   * Confidence mapping: high→LOW risk, medium→MEDIUM risk, low→HIGH risk
   * (higher confidence in discharge means lower occupancy risk)
   * @param item RawBedItem with discharge_prediction_confidence
   * @returns Risk tier or null if no prediction available
   */
  private calculateRiskTier(item: RawBedItem): 'HIGH' | 'MEDIUM' | 'LOW' | null {
    if (!item.discharge_prediction_confidence) return null;
    const confidenceMap: Record<string, 'HIGH' | 'MEDIUM' | 'LOW'> = {
      high: 'LOW',
      medium: 'MEDIUM',
      low: 'HIGH',
    };
    return confidenceMap[item.discharge_prediction_confidence] ?? null;
  }
}
