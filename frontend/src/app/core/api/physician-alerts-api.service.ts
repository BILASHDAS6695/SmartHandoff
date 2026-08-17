import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  PhysicianAlert,
  PhysicianAlertResolveRequest,
} from '../models/physician-alert.model';

/**
 * HTTP client for physician review alerts.
 *
 * Base path: /api/v1/physician-alerts
 */
@Injectable({ providedIn: 'root' })
export class PhysicianAlertsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/v1/physician-alerts`;

  /**
   * List physician alerts for the caller.
   * GET /api/v1/physician-alerts?status_filter=ACTIVE
   */
  listAlerts(statusFilter?: 'ACTIVE' | 'RESOLVED'): Observable<PhysicianAlert[]> {
    let params = new HttpParams();
    if (statusFilter) {
      params = params.set('status_filter', statusFilter);
    }
    return this.http.get<PhysicianAlert[]>(this.base, { params });
  }

  /**
   * Get a single physician alert.
   * GET /api/v1/physician-alerts/{alertId}
   */
  getAlert(alertId: string): Observable<PhysicianAlert> {
    return this.http.get<PhysicianAlert>(`${this.base}/${alertId}`);
  }

  /**
   * Resolve a physician alert.
   * PATCH /api/v1/physician-alerts/{alertId}/resolve
   */
  resolveAlert(alertId: string, payload: PhysicianAlertResolveRequest): Observable<PhysicianAlert> {
    return this.http.patch<PhysicianAlert>(`${this.base}/${alertId}/resolve`, payload);
  }
}
