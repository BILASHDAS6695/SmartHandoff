/**
 * Analytics Dashboard — consumes GET /api/v1/analytics/kpis.
 */
import { Component, OnInit, OnDestroy, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatSelectModule } from '@angular/material/select';
import { Subject, takeUntil } from 'rxjs';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import { AuthService } from '../../core/auth/auth.service';
import { AnalyticsApiService } from './analytics-api.service';
import { DischargeVolumeChartComponent } from './charts/discharge-volume-chart.component';
import { RiskDistributionChartComponent } from './charts/risk-distribution-chart.component';
import { HighRiskEncounter, KpiDataPoint, KpiResponse } from './analytics.models';

interface KpiCard {
  label: string;
  value: string;
  trend: string;
  trendClass: string;
}

interface HighRiskEncounterRow {
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
  imports: [CommonModule, MatSelectModule, DischargeVolumeChartComponent, RiskDistributionChartComponent],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.scss',
})
export class AnalyticsComponent implements OnInit, OnDestroy {
  private readonly router = inject(Router);
  private readonly authService = inject(AuthService);
  private readonly analyticsApi = inject(AnalyticsApiService);
  private readonly destroy$ = new Subject<void>();

  readonly selectedPeriod = signal<string>('Last 30 days');
  readonly selectedUnit = signal<string>('All Units');

  readonly availablePeriods = signal<string[]>(['Last 30 days', 'Last 7 days', 'Last 90 days']);
  /** Units the manager/admin can access, derived from the JWT `units` claim. */
  readonly availableUnits = computed<string[]>(() => {
    const userUnits = this.authService.currentUser()?.units ?? [];
    return ['All Units', ...userUnits];
  });

  readonly kpiCards = signal<KpiCard[]>([
    { label: 'Avg Discharge Time', value: '—', trend: 'No data', trendClass: 'neutral' },
    { label: '30-Day Readmission Rate', value: '—', trend: 'No data', trendClass: 'neutral' },
    { label: 'Med Recon Completion', value: '—', trend: 'No data', trendClass: 'neutral' },
    { label: 'Bed Utilisation', value: '—', trend: 'No data', trendClass: 'neutral' },
  ]);

  readonly highRiskEncounters = signal<HighRiskEncounterRow[]>([]);
  readonly kpiData = signal<KpiResponse['data']>([]);

  readonly isLoading = signal<boolean>(false);
  readonly isExportingCsv = signal<boolean>(false);
  readonly isExportingPdf = signal<boolean>(false);
  readonly exportError = signal<string | null>(null);
  readonly loadError = signal<string | null>(null);

  ngOnInit(): void {
    this.loadKpis();
    this.loadHighRiskEncounters();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private loadKpis(): void {
    this.isLoading.set(true);
    this.loadHighRiskEncounters();
    this.loadError.set(null);

    const filters = this.analyticsApi.filtersForPeriod(this.selectedPeriod());
    if (this.selectedUnit() !== 'All Units') {
      filters.unit = this.selectedUnit();
    }

    this.analyticsApi.getKpis(filters)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response: KpiResponse) => {
          this.kpiData.set(response.data ?? []);
          this.updateKpiCards(response);
          this.isLoading.set(false);
        },
        error: err => {
          this.loadError.set(err.message || 'Failed to load analytics.');
          this.isLoading.set(false);
        },
      });
  }

  private loadHighRiskEncounters(): void {
    const unit = this.selectedUnit() === 'All Units' ? undefined : this.selectedUnit();
    this.analyticsApi.getHighRiskEncounters(unit)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: response => {
          this.highRiskEncounters.set((response.data ?? []).map((e: HighRiskEncounter) => ({
            patientMasked: e.patient_masked,
            unit: e.unit ?? '—',
            riskScore: e.risk_score ?? 0,
            riskLabel: e.risk_label,
            dischargeDate: e.discharge_date ? new Date(e.discharge_date).toLocaleDateString('en-US') : '—',
            followUpStatus: e.follow_up_status,
            followUpClass: this.followUpClass(e.follow_up_status),
          })));
        },
        error: err => {
          console.error('Failed to load high-risk encounters:', err);
        },
      });
  }

  private updateKpiCards(response: KpiResponse): void {
    const data = response.data ?? [];

    const formatPct = (v: number | null | undefined) => v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`;
    const formatHours = (v: number | null | undefined) => v === null || v === undefined ? '—' : `${v.toFixed(1)}h`;

    // Average a metric across all rows in the selected period. This makes
    // period filters show different values for census-style metrics instead of
    // always showing the latest day's snapshot.
    const periodAvg = (field: keyof KpiResponse['data'][number]): number | null => {
      const values = data
        .map((d) => d[field])
        .filter((v): v is number => v !== null && v !== undefined);
      return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    };

    // Average discharge documentation time across the period. Backend returns
    // minutes; convert to hours for display.
    const dischargeTimeMin = ((): number | null => {
      const values = data
        .map((d) => d.avg_discharge_doc_time_min)
        .filter((v): v is number => v !== null && v !== undefined);
      return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    })();

    // Readmission and med-recon rates must be weighted by discharge volume,
    // otherwise days/units with zero discharges dilute the average.
    const weightedRate = (field: 'readmission_rate_30d' | 'med_recon_completion_rate'): number | null => {
      let numerator = 0;
      let denominator = 0;
      for (const d of data) {
        const rate = d[field];
        const count = d.discharge_count;
        if (rate !== null && rate !== undefined && count !== null && count !== undefined && count > 0) {
          numerator += rate * count;
          denominator += count;
        }
      }
      return denominator > 0 ? numerator / denominator : null;
    };

    const bedUtil = periodAvg('bed_utilisation_pct');

    this.kpiCards.set([
      { label: 'Avg Discharge Time', value: formatHours(dischargeTimeMin === null ? null : dischargeTimeMin / 60.0), trend: 'Latest period', trendClass: 'neutral' },
      { label: '30-Day Readmission Rate', value: formatPct(weightedRate('readmission_rate_30d')), trend: 'Latest period', trendClass: 'neutral' },
      { label: 'Med Recon Completion', value: formatPct(weightedRate('med_recon_completion_rate')), trend: 'Latest period', trendClass: 'neutral' },
      { label: 'Bed Utilisation', value: bedUtil === null ? '—' : `${bedUtil.toFixed(1)}%`, trend: 'Latest period', trendClass: 'neutral' },
    ]);
  }

  private followUpClass(status: string): string {
    switch (status) {
      case 'Completed':
        return 'completed';
      case 'Scheduled':
        return 'scheduled';
      default:
        return 'pending';
    }
  }

  onPeriodChange(period: string): void {
    this.selectedPeriod.set(period);
    this.loadKpis();
  }

  onUnitChange(unit: string): void {
    this.selectedUnit.set(unit);
    this.loadKpis();
    this.loadHighRiskEncounters();
  }

  onExportCsv(): void {
    this.isExportingCsv.set(true);
    this.exportError.set(null);

    try {
      const rows = this.buildExportRows();
      if (rows.length === 0) {
        this.exportError.set('No data to export.');
        this.isExportingCsv.set(false);
        return;
      }

      const headers = Object.keys(rows[0]);
      const csv = [
        headers.join(','),
        ...rows.map(row =>
          headers
            .map(h => {
              const value = (row as Record<string, unknown>)[h];
              const text = value === null || value === undefined ? '' : String(value);
              return `"${text.replace(/"/g, '""')}"`;
            })
            .join(','),
        ),
      ].join('\n');

      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      this.downloadBlob(blob, `analytics-${this.selectedPeriod().replace(/\s+/g, '_').toLowerCase()}.csv`);
    } catch (err) {
      this.exportError.set(err instanceof Error ? err.message : 'CSV export failed.');
    } finally {
      this.isExportingCsv.set(false);
    }
  }

  onExportPdf(): void {
    this.isExportingPdf.set(true);
    this.exportError.set(null);

    try {
      const rows = this.buildExportRows();
      if (rows.length === 0) {
        this.exportError.set('No data to export.');
        this.isExportingPdf.set(false);
        return;
      }

      const doc = new jsPDF({ orientation: 'landscape' });
      const title = `Analytics Report — ${this.selectedPeriod()}${this.selectedUnit() !== 'All Units' ? ' — ' + this.selectedUnit() : ''}`;
      doc.text(title, 14, 16);

      autoTable(doc, {
        startY: 24,
        head: [Object.keys(rows[0])],
        body: rows.map(row => Object.values(row).map(v => v ?? '')),
        styles: { fontSize: 9, overflow: 'linebreak' },
        headStyles: { fillColor: [37, 99, 235] },
        didDrawPage: data => {
          doc.setFontSize(8);
          doc.text(`Exported ${new Date().toLocaleString()}`, 14, doc.internal.pageSize.height - 10);
        },
      });

      doc.save(`analytics-${this.selectedPeriod().replace(/\s+/g, '_').toLowerCase()}.pdf`);
    } catch (err) {
      this.exportError.set(err instanceof Error ? err.message : 'PDF export failed.');
    } finally {
      this.isExportingPdf.set(false);
    }
  }

  private buildExportRows(): Record<string, string | number>[] {
    const data = this.kpiData();
    if (!data || data.length === 0) {
      return [];
    }

    const formatPct = (v: number | null | undefined) => v === null || v === undefined ? '' : `${(v * 100).toFixed(1)}%`;
    const formatMin = (v: number | null | undefined) => v === null || v === undefined ? '' : `${(v / 60).toFixed(1)}h`;

    return data.map((point: KpiDataPoint) => ({
      Date: point.date,
      Unit: point.unit,
      Discharges: point.discharge_count ?? 0,
      'Avg Discharge Time': formatMin(point.avg_discharge_doc_time_min),
      '30-Day Readmission Rate': formatPct(point.readmission_rate_30d),
      'Med Recon Completion': formatPct(point.med_recon_completion_rate),
      'Bed Utilisation': formatPct(point.bed_utilisation_pct),
    }));
  }

  private downloadBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  getRiskChipClass(label: string): string {
    return label === 'HIGH' ? 'high' : 'med';
  }
}


