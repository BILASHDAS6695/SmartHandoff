/**
 * Service for fetching KPI analytics data from the backend.
 *
 * Design refs:
 *   design.md §3.3 — GET /api/v1/analytics/kpis
 *   US-061 Technical Notes — query params: from, to, unit
 *   US-061 AC Scenario 1 — default 30-day range
 *   US-061 AC Scenario 2 — filter updates reflected within 2 s
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { KpiFilterParams, KpiResponse } from './analytics.models';

@Injectable({ providedIn: 'root' })
export class AnalyticsApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = '/api/v1/analytics';

  /**
   * Fetch KPI data for the given filter parameters.
   * All three params are forwarded as URL query strings.
   * The JWT is attached automatically by the JwtInterceptor (core/auth).
   */
  getKpis(filters: KpiFilterParams): Observable<KpiResponse> {
    let params = new HttpParams()
      .set('from', filters.from)
      .set('to', filters.to);

    if (filters.unit) {
      params = params.set('unit', filters.unit);
    }

    return this.http.get<KpiResponse>(`${this.baseUrl}/kpis`, { params });
  }

  /**
   * Return default filter params: last 30 days, no unit filter.
   * Used to initialise the filter form and URL query params on first load.
   */
  defaultFilters(): KpiFilterParams {
    const today = new Date();
    const from = new Date(today);
    from.setDate(today.getDate() - 30);

    return {
      from: from.toISOString().split('T')[0],
      to: today.toISOString().split('T')[0],
    };
  }
}
