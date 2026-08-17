/**
 * EncountersApiService — typed HTTP client for the encounters REST API.
 * Provides methods for fetching encounter data and event history.
 *
 * US-048 TASK-005
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env/environment';
import { AdtEventPayload } from '@core/signalr/signalr.models';
import { PatientListQuery, PatientListResponse } from '../../features/patients/models/patient.model';

export interface RecentEventsResponse {
  events: AdtEventPayload[];
  /** ISO-8601 timestamp of the most recent event in this response */
  latestEventTime: string;
}

/** Encounter create request payload. */
export interface EncounterCreateRequest {
  patient_id: string;
  status: 'REGISTERED' | 'PRE_ADMISSION' | 'ADMITTED' | 'TRANSFERRED' | 'DISCHARGED';
  unit: string;
  risk_tier: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
  event_type?: 'A01' | 'A02' | 'A03' | 'A04' | 'A08' | null;
}

/** Encounter update request payload. */
export interface EncounterUpdateRequest {
  status?: 'REGISTERED' | 'PRE_ADMISSION' | 'ADMITTED' | 'TRANSFERRED' | 'DISCHARGED';
  unit?: string;
  risk_tier?: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
  event_type?: 'A01' | 'A02' | 'A03' | 'A04' | 'A08' | null;
}

/** Encounter write response payload. */
export interface EncounterWriteResponse {
  id: string;
  patient_id: string;
  status: string;
  unit: string | null;
  risk_tier: string;
  created_at: string;
  updated_at: string;
}

@Injectable({ providedIn: 'root' })
export class EncountersApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/encounters`;

  /**
   * Fetches paginated encounter-level records (one row per encounter/registration).
   * @param query - Unit, optional search term, status, page, and page_size
   */
  listEncounters(query: PatientListQuery): Observable<PatientListResponse> {
    let params = new HttpParams()
      .set('unit', query.unit)
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.page_size ?? 25));

    if (query.search?.trim()) {
      params = params.set('search', query.search.trim());
    }

    if (query.status?.trim()) {
      params = params.set('status', query.status.trim());
    }

    if (query.patient_id?.trim()) {
      params = params.set('patient_id', query.patient_id.trim());
    }

    return this.http.get<PatientListResponse>(this.baseUrl, { params });
  }

  /**
   * Fetches ADT events that occurred after the given ISO-8601 timestamp.
   * Used as a REST fallback after SignalR reconnects to backfill missed events.
   *
   * @param since - ISO-8601 timestamp of the last event received before disconnect
   * @returns Observable of recent events response
   */
  getRecentEvents(since: string): Observable<RecentEventsResponse> {
    const params = new HttpParams().set('since', since);
    return this.http.get<RecentEventsResponse>(`${this.baseUrl}/recent-events`, {
      params,
    });
  }

  /**
   * Creates a new encounter for a patient.
   * POST /api/v1/encounters
   */
  createEncounter(payload: EncounterCreateRequest): Observable<EncounterWriteResponse> {
    return this.http.post<EncounterWriteResponse>(this.baseUrl, payload);
  }

  /**
   * Updates an existing encounter (transfer, discharge, or update).
   * PATCH /api/v1/encounters/{encounter_id}
   */
  updateEncounter(encounterId: string, payload: EncounterUpdateRequest): Observable<EncounterWriteResponse> {
    return this.http.patch<EncounterWriteResponse>(`${this.baseUrl}/${encounterId}`, payload);
  }
}
