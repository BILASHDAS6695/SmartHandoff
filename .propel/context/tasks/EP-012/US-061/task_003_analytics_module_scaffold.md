---
id: TASK-003
title: "Angular AnalyticsModule — Lazy-Loaded Module Scaffold, Routing & API Client Service"
user_story: US-061
epic: EP-012
sprint: 2
layer: Frontend / Module
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-061, US-047, TR-002]
---

# TASK-003: Angular AnalyticsModule — Lazy-Loaded Module Scaffold, Routing & API Client Service

> **Story:** US-061 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Frontend / Module | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task creates the Angular lazy-loaded `AnalyticsModule` feature shell at route `/analytics` with:

- Lazy-loaded route registered in the root router (no eager loading — TR-002 bundle budget constraint)
- `AnalyticsComponent` as the top-level routed component (shell, not yet the charts — those are TASK-005)
- `AnalyticsApiService` that calls `GET /api/v1/analytics/kpis` and maps the response to typed observables
- `AuthGuard` applying `MANAGER` / `ADMIN` role check client-side (mirrors server-side RBAC from TASK-002)
- Module-level imports: `ng2-charts`, `ReactiveFormsModule`, `MatDatepickerModule`, `MatSelectModule`

**Design references:**
- design.md §3.4 — Frontend Module Architecture: `features/analytics/` — FR-073 KPI dashboards (Chart.js)
- design.md §4.1 — Chart.js 4.x; `ng2-charts` Angular wrapper; Angular 17 standalone components
- design.md TR-002 — Main chunk <500 KB; all feature modules lazy-loaded
- design.md ADR-005 — Angular 17 PWA with lazy-loaded feature modules per role

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Route `/analytics` lazy-loads and resolves; API service fetches KPI data with 30-day default |
| Scenario 4 | `AuthGuard` prevents nurse role from reaching the route client-side (defence-in-depth — server enforces 403) |

---

## Implementation Steps

### 1. Create file structure

```bash
mkdir -p smarthandoff-angular/src/app/features/analytics
touch smarthandoff-angular/src/app/features/analytics/analytics.routes.ts
touch smarthandoff-angular/src/app/features/analytics/analytics.component.ts
touch smarthandoff-angular/src/app/features/analytics/analytics.component.html
touch smarthandoff-angular/src/app/features/analytics/analytics.component.scss
touch smarthandoff-angular/src/app/features/analytics/analytics-api.service.ts
touch smarthandoff-angular/src/app/features/analytics/analytics.models.ts
```

### 2. Define typed models in `analytics.models.ts`

```typescript
/**
 * Client-side models matching the KpiResponse / KpiDataPoint Pydantic schemas
 * returned by GET /api/v1/analytics/kpis.
 *
 * IMPORTANT — PHI guardrail:
 *   No PHI fields are modelled here. All fields are aggregated metrics only.
 *   See US-061 AC Scenario 3.
 */

export interface KpiDataPoint {
  /** ISO 8601 date string — e.g. "2026-07-01" */
  date: string;
  unit: string;
  avg_discharge_doc_time_min: number | null;
  readmission_rate_30d: number | null;
  med_recon_completion_rate: number | null;
  bed_utilisation_pct: number | null;
  agent_task_success_rate: number | null;
}

export interface KpiResponse {
  from_date: string;
  to_date: string;
  unit: string | null;
  data: KpiDataPoint[];
  total_rows: number;
}

/** Filter parameters sent as URL query params to the API and reflected in the browser URL. */
export interface KpiFilterParams {
  from: string;   // ISO 8601 date
  to: string;     // ISO 8601 date
  unit?: string;
}
```

### 3. Implement `AnalyticsApiService` in `analytics-api.service.ts`

```typescript
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
```

### 4. Create the `AnalyticsComponent` shell in `analytics.component.ts`

```typescript
/**
 * Top-level shell component for the /analytics route.
 *
 * Responsibilities at this layer (shell only):
 *   - Inject AnalyticsApiService and ActivatedRoute
 *   - Initialise filter params from URL query params (or defaults)
 *   - Expose a KpiResponse$ observable for child chart components to consume
 *
 * Filter bar (TASK-004) and chart components (TASK-005) will be composed into
 * the template of this shell.
 *
 * Design refs:
 *   design.md §3.4 — features/analytics/ module
 *   US-061 DoD — AnalyticsComponent Angular lazy-loaded module
 */
import { AsyncPipe } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, switchMap } from 'rxjs';

import { AnalyticsApiService } from './analytics-api.service';
import { KpiFilterParams, KpiResponse } from './analytics.models';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [AsyncPipe],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.scss',
})
export class AnalyticsComponent implements OnInit {
  private readonly apiService = inject(AnalyticsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  kpiData$!: Observable<KpiResponse>;

  ngOnInit(): void {
    // Derive filter params from URL query params; fall back to defaults
    this.kpiData$ = this.route.queryParams.pipe(
      switchMap((params) => {
        const defaults = this.apiService.defaultFilters();
        const filters: KpiFilterParams = {
          from: params['from'] ?? defaults.from,
          to: params['to'] ?? defaults.to,
          unit: params['unit'] ?? undefined,
        };
        return this.apiService.getKpis(filters);
      }),
    );
  }

  /**
   * Called by the filter bar (TASK-004) when the manager changes the date range or unit.
   * Updates URL query params, which triggers kpiData$ re-fetch via route.queryParams.
   */
  onFilterChange(filters: KpiFilterParams): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        from: filters.from,
        to: filters.to,
        unit: filters.unit ?? null,
      },
      queryParamsHandling: 'merge',
    });
  }
}
```

### 5. Create minimal `analytics.component.html` shell

```html
<!-- analytics.component.html — shell template; filter bar and charts composed in TASK-004/005 -->
<section class="analytics-shell" aria-label="KPI Analytics Dashboard">
  <header class="analytics-header">
    <h1>Analytics Dashboard</h1>
    <!-- app-analytics-filter-bar composed here in TASK-004 -->
  </header>

  <ng-container *ngIf="kpiData$ | async as kpiData; else loading">
    <div class="kpi-charts-grid">
      <!-- Individual chart components composed here in TASK-005 -->
      <p>{{ kpiData.total_rows }} data points loaded ({{ kpiData.from_date }} – {{ kpiData.to_date }})</p>
    </div>
  </ng-container>

  <ng-template #loading>
    <div role="status" aria-live="polite" class="loading-state">Loading KPI data…</div>
  </ng-template>
</section>
```

### 6. Define analytics routes in `analytics.routes.ts`

```typescript
import { Routes } from '@angular/router';
import { roleGuard } from '@core/auth/role.guard';

export const ANALYTICS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./analytics.component').then((m) => m.AnalyticsComponent),
    canActivate: [roleGuard(['MANAGER', 'ADMIN'])],
    title: 'Analytics Dashboard — SmartHandoff',
  },
];
```

### 7. Register lazy-loaded route in root `app.routes.ts`

Add the analytics entry to the root routes array. Do not eagerly import `AnalyticsComponent`:

```typescript
{
  path: 'analytics',
  loadChildren: () =>
    import('./features/analytics/analytics.routes').then((m) => m.ANALYTICS_ROUTES),
},
```

### 8. Add `ng2-charts` and `chart.js` dependencies

```bash
cd smarthandoff-angular
npm install chart.js@^4.0.0 ng2-charts@^6.0.0
```

Confirm `package.json` peer-dependency versions align:
- `chart.js`: `^4.4.0`
- `ng2-charts`: `^6.0.0` (supports Chart.js 4.x)

---

## Validation Checklist

- [ ] Navigating to `/analytics` lazy-loads the module (no eager chunk in main bundle)
- [ ] `AnalyticsComponent` initialises `kpiData$` from URL query params on first load with 30-day defaults
- [ ] `AnalyticsApiService.getKpis()` sends `from`, `to`, `unit` as URL query params
- [ ] `ANALYTICS_ROUTES` applies `roleGuard(['MANAGER', 'ADMIN'])` — navigating as NURSE redirects to 403/unauthorised page
- [ ] `chart.js@^4` and `ng2-charts@^6` present in `package.json`
- [ ] `analytics.component.html` has `aria-label` on the section and a loading state with `role="status" aria-live="polite"`
- [ ] No PHI-related types or fields in `analytics.models.ts`
- [ ] `ng build` passes with no bundle budget warnings for the analytics chunk

---

## Files Created / Modified

| File | Action |
|------|--------|
| `smarthandoff-angular/src/app/features/analytics/analytics.models.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics-api.service.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.html` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.scss` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics.routes.ts` | Create |
| `smarthandoff-angular/src/app/app.routes.ts` | Modify — add analytics lazy-load entry |
| `smarthandoff-angular/package.json` | Modify — add chart.js and ng2-charts |
