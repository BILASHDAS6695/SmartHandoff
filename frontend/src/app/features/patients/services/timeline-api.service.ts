import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';

/** A single realtime event in the encounter timeline. */
export interface TimelineEvent {
  event_type: string;
  title: string;
  description: string | null;
  timestamp: string | null;
  status: string | null;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
}

/** Response envelope for GET /api/v1/encounters/{id}/timeline. */
export interface EncounterTimelineResponse {
  encounter_id: string;
  events: TimelineEvent[];
  total: number;
}

/**
 * HTTP client for the encounter realtime timeline endpoint.
 *
 * Source: realtime encounter timeline (US-028 follow-up).
 * Base path: /api/v1/encounters/{encounterId}/timeline
 */
@Injectable({ providedIn: 'root' })
export class TimelineApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/encounters`;

  /**
   * Fetches the chronological timeline for a specific encounter.
   * @param encounterId - Encounter UUID
   */
  getEncounterTimeline(encounterId: string): Observable<EncounterTimelineResponse> {
    return this.http.get<EncounterTimelineResponse>(
      `${this.baseUrl}/${encounterId}/timeline`
    );
  }
}
