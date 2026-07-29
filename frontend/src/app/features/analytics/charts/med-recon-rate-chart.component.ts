/**
 * Gauge chart (half-doughnut) — medication reconciliation completion rate.
 *
 * Displays the latest value in the dataset as a gauge needle indicator.
 * Chart.js does not have a native gauge type; half-doughnut with rotation
 * simulates a gauge (standard Chart.js pattern).
 *
 * Design refs:
 *   US-061 DoD — med_recon_rate → Gauge chart
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';

@Component({
  selector: 'app-med-recon-rate-chart',
  standalone: true,
  imports: [NgChartsModule],
  template: `
    @if (latestRate !== null) {
      <canvas
        baseChart
        [data]="chartData"
        [options]="chartOptions"
        type="doughnut"
        role="img"
        [attr.aria-label]="'Medication reconciliation completion rate gauge: ' + latestRatePct + '%'"
      ></canvas>
      <p class="gauge-label" aria-hidden="true">{{ latestRatePct }}% complete</p>
    } @else {
      <p class="no-data" role="status">No medication reconciliation data available.</p>
    }
  `,
  styleUrl: './med-recon-rate-chart.component.scss',
})
export class MedReconRateChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  latestRate: number | null = null;
  chartData: ChartConfiguration<'doughnut'>['data'] = { datasets: [] };

  readonly chartOptions: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    circumference: 180,
    rotation: -90,
    cutout: '75%',
    plugins: {
      legend: { display: false },
      title: { display: true, text: 'Medication Reconciliation Completion Rate' },
      tooltip: { enabled: false },
    },
  };

  get latestRatePct(): number {
    return this.latestRate !== null ? Math.round(this.latestRate * 100) : 0;
  }

  ngOnChanges(): void {
    const sorted = [...this.data].sort(
      (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
    );
    const latest = sorted.find((d) => d.med_recon_completion_rate !== null);
    this.latestRate = latest?.med_recon_completion_rate ?? null;

    if (this.latestRate !== null) {
      const pct = Math.round(this.latestRate * 100);
      this.chartData = {
        datasets: [
          {
            data: [pct, 100 - pct],
            backgroundColor: ['rgba(72, 187, 120, 0.9)', 'rgba(226, 232, 240, 0.4)'],
            borderWidth: 0,
          },
        ],
      };
    }
  }
}
