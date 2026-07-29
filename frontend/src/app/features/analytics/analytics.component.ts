/**
 * Top-level shell component for the /analytics route.
 *
 * Responsibilities at this layer (shell only):
 *   - Inject AnalyticsApiService and ActivatedRoute
 *   - Initialise filter params from URL query params (or defaults)
 *   - Expose a KpiResponse$ observable for child chart components to consume
 *   - Populate availableUnits from the current user's JWT claims
 *   - Handle CSV and PDF export actions
 *
 * Filter bar (TASK-004) and chart components (TASK-005) will be composed into
 * the template of this shell.
 *
 * Design refs:
 *   design.md §3.4 — features/analytics/ module
 *   US-061 DoD — AnalyticsComponent Angular lazy-loaded module
 *   US-056 TASK-005 — AuthService in-memory JWT storage
 *   US-063 — Export CSV/PDF from analytics dashboard
 */
import { AsyncPipe, NgIf } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, switchMap } from 'rxjs';

import { AuthService } from '@core/auth/auth.service';
import { AnalyticsApiService } from './analytics-api.service';
import { AnalyticsExportService } from './services/analytics-export.service';
import { AnalyticsFilterBarComponent } from './filter-bar/analytics-filter-bar.component';
import { AgentSuccessRateChartComponent } from './charts/agent-success-rate-chart.component';
import { BedUtilisationChartComponent } from './charts/bed-utilisation-chart.component';
import { DischargeTimeChartComponent } from './charts/discharge-time-chart.component';
import { MedReconRateChartComponent } from './charts/med-recon-rate-chart.component';
import { ReadmissionRateChartComponent } from './charts/readmission-rate-chart.component';
import { KpiFilterParams, KpiResponse } from './analytics.models';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [
    AsyncPipe,
    NgIf,
    AnalyticsFilterBarComponent,
    DischargeTimeChartComponent,
    ReadmissionRateChartComponent,
    MedReconRateChartComponent,
    BedUtilisationChartComponent,
    AgentSuccessRateChartComponent,
  ],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.scss',
})
export class AnalyticsComponent implements OnInit {
  private readonly authService = inject(AuthService);
  private readonly apiService = inject(AnalyticsApiService);
  private readonly exportService = inject(AnalyticsExportService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  kpiData$!: Observable<KpiResponse>;
  initialFilters!: KpiFilterParams;
  availableUnits: string[] = [];

  isExportingCsv = false;
  isExportingPdf = false;
  exportError: string | null = null;

  ngOnInit(): void {
    // Initialise filters from defaults
    const defaults = this.apiService.defaultFilters();
    this.initialFilters = {
      from: this.route.snapshot.queryParams['from'] ?? defaults.from,
      to: this.route.snapshot.queryParams['to'] ?? defaults.to,
      unit: this.route.snapshot.queryParams['unit'] ?? undefined,
    };

    // Populate available units from the current user's JWT claims (manager's accessible units).
    // This satisfies US-061 DoD: "Unit filter dropdown populated from app_user.units"
    // AuthService.currentUser() is a computed signal from the decoded JWT payload.
    this.availableUnits = this.authService.currentUser()?.units ?? [];

    // Derive KPI data observable from URL query params
    this.kpiData$ = this.route.queryParams.pipe(
      switchMap((params) => {
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

  onExportCsv(): void {
    this.isExportingCsv = true;
    this.exportError = null;
    this.exportService
      .downloadCsv(this.initialFilters.from, this.initialFilters.to)
      .subscribe({
        next: () => (this.isExportingCsv = false),
        error: (err) => {
          this.isExportingCsv = false;
          this.exportError = 'CSV export failed. Please try again.';
          console.error('[AnalyticsDashboard] CSV export error:', err);
        },
      });
  }

  onExportPdf(): void {
    this.isExportingPdf = true;
    this.exportError = null;
    this.exportService
      .initiatePdfExport(this.initialFilters.from, this.initialFilters.to)
      .subscribe({
        next: () => (this.isExportingPdf = false),
        error: (err) => {
          this.isExportingPdf = false;
          this.exportError = 'PDF export failed or timed out. Please try again.';
          console.error('[AnalyticsDashboard] PDF export error:', err);
        },
      });
  }
}


