import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { BedDto, BedItem } from '../models/bed.model';
import { environment } from '@environments/environment';

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
    return this.http.get<BedItem[]>(this.apiBase, { params }).pipe(
      map(items => items.map(item => this.mapBedItemToDto(item)))
    );
  }

  /**
   * Transforms a BedItem (from API) to BedDto (for UI).
   * Extracts essential fields and calculates derived data like risk tier.
   * @param item BedItem from API response
   * @returns BedDto suitable for bed board UI rendering
   */
  private mapBedItemToDto(item: BedItem): BedDto {
    return {
      bedId: item.bedId,
      unit: item.unit,
      status: item.bedStatus,
      patientName: null, // Patient name sourced from separate Patient API (privacy boundary)
      predictedDischargeTime: item.predictedDischargeTime,
      assignedNurse: null, // Assigned nurse sourced from Nurse assignment API
      riskTier: this.calculateRiskTier(item), // Derive from confidence level (US-036)
    };
  }

  /**
   * Calculates patient risk tier based on discharge prediction confidence.
   * Confidence mapping: high→LOW risk, medium→MEDIUM risk, low→HIGH risk
   * (higher confidence in discharge means lower occupancy risk)
   * @param item BedItem with dischargePredictionConfidence
   * @returns Risk tier or null if no prediction available
   */
  private calculateRiskTier(item: BedItem): 'HIGH' | 'MEDIUM' | 'LOW' | null {
    if (!item.dischargePredictionConfidence) return null;
    const confidenceMap: Record<string, 'HIGH' | 'MEDIUM' | 'LOW'> = {
      high: 'LOW',
      medium: 'MEDIUM',
      low: 'HIGH',
    };
    return confidenceMap[item.dischargePredictionConfidence] ?? null;
  }
}
