import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import {
  InteractionAlert,
  AlertResolutionPayload,
} from '../models/interaction-alert.model';

/**
 * HTTP client for interaction alert endpoints.
 * Source: US-031 Interaction Alert API.
 *
 * Base path: /api/v1/alerts
 */
@Injectable({ providedIn: 'root' })
export class InteractionAlertApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/alerts`;

  /**
   * Fetches full alert detail including drug pair and RxNav description.
   * GET /api/v1/alerts/{alertId}
   */
  getAlert(alertId: string): Observable<InteractionAlert> {
    return this.http.get<InteractionAlert>(`${this.base}/${alertId}`);
  }

  /**
   * Submits clinician resolution for a drug interaction alert.
   * PATCH /api/v1/alerts/{alertId}/resolve
   *
   * On success, the backend sets status = RESOLVED and emits a SignalR
   * `alert_resolved` event to the encounter group.
   */
  resolveAlert(
    alertId: string,
    payload: AlertResolutionPayload
  ): Observable<InteractionAlert> {
    return this.http.patch<InteractionAlert>(
      `${this.base}/${alertId}/resolve`,
      payload
    );
  }
}
