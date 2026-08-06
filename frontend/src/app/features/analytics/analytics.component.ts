/**
 * Analytics Dashboard — matches Hi-Fi wireframe SCR-009.
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatSelectModule } from '@angular/material/select';

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
export class AnalyticsComponent implements OnInit {
  private readonly router = inject(Router);

  readonly selectedPeriod = signal<string>('Last 30 days');
  readonly selectedUnit = signal<string>('All Units');

  readonly availablePeriods = signal<string[]>(['Last 30 days', 'Last 7 days', 'Last 90 days']);
  readonly availableUnits = signal<string[]>(['All Units', '4-West', '3-North', 'ICU']);

  readonly kpiCards = signal<KpiCard[]>([
    { label: 'Avg Discharge Time', value: '4.2h', trend: '↓ −0.8h vs prev period ✓ Improving', trendClass: 'down-good' },
    { label: '30-Day Readmission Rate', value: '8.3%', trend: '↓ −1.1% vs prev period ✓ Improving', trendClass: 'down-good' },
    { label: 'Med Recon Completion', value: '96.4%', trend: '↑ +2.1% vs prev period ✓ Improving', trendClass: 'up-good' },
    { label: 'Bed Utilisation', value: '87%', trend: '↑ +3% vs prev period', trendClass: 'up-good' },
  ]);

  readonly highRiskEncounters = signal<HighRiskEncounter[]>([
    { patientMasked: '●●● #2041', unit: '4-West', riskScore: 0.82, riskLabel: 'HIGH', dischargeDate: '2026-07-14', followUpStatus: '✓ Booked Jul 21', followUpClass: 'good' },
    { patientMasked: '●●● #2038', unit: 'ICU', riskScore: 0.79, riskLabel: 'HIGH', dischargeDate: '2026-07-13', followUpStatus: '✓ Booked Jul 20', followUpClass: 'good' },
    { patientMasked: '●●● #2035', unit: '3-North', riskScore: 0.76, riskLabel: 'HIGH', dischargeDate: '2026-07-12', followUpStatus: '⏳ Pending', followUpClass: 'pending' },
    { patientMasked: '●●● #2031', unit: '4-West', riskScore: 0.71, riskLabel: 'HIGH', dischargeDate: '2026-07-11', followUpStatus: '✓ Booked Jul 18', followUpClass: 'good' },
    { patientMasked: '●●● #2027', unit: '5-East', riskScore: 0.68, riskLabel: 'MED', dischargeDate: '2026-07-10', followUpStatus: '✓ Booked Jul 24', followUpClass: 'good' },
  ]);

  readonly isExportingCsv = signal<boolean>(false);
  readonly isExportingPdf = signal<boolean>(false);
  readonly exportError = signal<string | null>(null);

  ngOnInit(): void {
    // Static preview — no API calls
  }

  onPeriodChange(period: string): void {
    this.selectedPeriod.set(period);
  }

  onUnitChange(unit: string): void {
    this.selectedUnit.set(unit);
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


