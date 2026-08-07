/**
 * Analytics Dashboard — consumes GET /api/v1/analytics/kpis.
 */
import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatSelectModule } from '@angular/material/select';
import { Subject, takeUntil } from 'rxjs';
import { AnalyticsApiService } from './analytics-api.service';
import { KpiResponse } from './analytics.models';

interface KpiCard {
  label: string;
  value: string;
  trend: string;
  trendClass: string;
}

interface HighRiskEncounter {
  patientMasked: string;
  unit: string;
  riskScore: number;
  riskLabel: string;
  dischargeDate: string;
  followUpStatus: string;
  followUpClass: string;
}

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, MatSelectModule],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.scss',
})
export class AnalyticsComponent implements OnInit, OnDestroy {
  private readonly router = inject(Router);
  private readonly analyticsApi = inject(AnalyticsApiService);
  private readonly destroy$ = new Subject<void>();

  readonly selectedPeriod = signal<string>('Last 30 days');
  readonly selectedUnit = signal<string>('All Units');

  readonly availablePeriods = signal<string[]>(['Last 30 days', 'Last 7 days', 'Last 90 days']);
  readonly availableUnits = signal<string[]>(['All Units', '4-West', '3-North', 'ICU', 'CCU', 'MED', 'PEDS', 'SURG', 'General']);

  readonly kpiCards = signal<KpiCard[]>([
    { label: 'Avg Discharge Time', value: '—', trend: 'No data', trendClass: 'neutral' },
    { label: '30-Day Readmission Rate', value: '—', trend: 'No data', trendClass: 'neutral' },
    { label: 'Med Recon Completion', value: '—', trend: 'No data', trendClass: 'neutral' },
    { label: 'Bed Utilisation', value: '—', trend: 'No data', trendClass: 'neutral' },
  ]);

  readonly highRiskEncounters = signal<HighRiskEncounter[]>([]);

  readonly isLoading = signal<boolean>(false);
  readonly isExportingCsv = signal<boolean>(false);
  readonly isExportingPdf = signal<boolean>(false);
  readonly exportError = signal<string | null>(null);
  readonly loadError = signal<string | null>(null);

  ngOnInit(): void {
    this.loadKpis();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private loadKpis(): void {
    this.isLoading.set(true);
    this.loadError.set(null);

    const filters = this.analyticsApi.defaultFilters();
    if (this.selectedUnit() !== 'All Units') {
      filters.unit = this.selectedUnit();
    }

    this.analyticsApi.getKpis(filters)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response: KpiResponse) => {
          this.updateKpiCards(response);
          this.isLoading.set(false);
        },
        error: err => {
          this.loadError.set(err.message || 'Failed to load analytics.');
          this.isLoading.set(false);
        },
      });
  }

  private updateKpiCards(response: KpiResponse): void {
    const data = response.data ?? [];
    const last = data[data.length - 1];

    const formatPct = (v: number | null) => v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`;
    const formatHours = (v: number | null) => v === null || v === undefined ? '—' : `${v.toFixed(1)}h`;

    this.kpiCards.set([
      { label: 'Avg Discharge Time', value: formatHours(last?.avg_discharge_doc_time_min), trend: 'Latest period', trendClass: 'neutral' },
      { label: '30-Day Readmission Rate', value: formatPct(last?.readmission_rate_30d), trend: 'Latest period', trendClass: 'neutral' },
      { label: 'Med Recon Completion', value: formatPct(last?.med_recon_completion_rate), trend: 'Latest period', trendClass: 'neutral' },
      { label: 'Bed Utilisation', value: formatPct(last?.bed_utilisation_pct), trend: 'Latest period', trendClass: 'neutral' },
    ]);
  }

  onPeriodChange(period: string): void {
    this.selectedPeriod.set(period);
    // TODO: adjust date range based on period selection
    this.loadKpis();
  }

  onUnitChange(unit: string): void {
    this.selectedUnit.set(unit);
    this.loadKpis();
  }

  onExportCsv(): void {
    this.isExportingCsv.set(true);
    this.exportError.set(null);
    setTimeout(() => {
      this.isExportingCsv.set(false);
    }, 1000);
  }

  onExportPdf(): void {
    this.isExportingPdf.set(true);
    this.exportError.set(null);
    setTimeout(() => {
      this.isExportingPdf.set(false);
    }, 1000);
  }

  getRiskChipClass(label: string): string {
    return label === 'HIGH' ? 'high' : 'med';
  }
}


