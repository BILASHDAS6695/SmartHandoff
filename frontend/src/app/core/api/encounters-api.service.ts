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

export interface RecentEventsResponse {
  events: AdtEventPayload[];
  /** ISO-8601 timestamp of the most recent event in this response */
  latestEventTime: string;
}

@Injectable({ providedIn: 'root' })
export class EncountersApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/encounters`;

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
}
