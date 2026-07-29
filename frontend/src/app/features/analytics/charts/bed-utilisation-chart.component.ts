/**
 * Doughnut chart — bed utilisation percentage (latest value).
 *
 * Design refs:
 *   US-061 DoD — bed_utilisation → Doughnut chart
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';

@Component({
  selector: 'app-bed-utilisation-chart',
  standalone: true,
  imports: [NgChartsModule],
  template: `
    @if (latestPct !== null) {
      <canvas
        baseChart
        [data]="chartData"
        [options]="chartOptions"
        type="doughnut"
        role="img"
        [attr.aria-label]="'Bed utilisation doughnut chart: ' + latestPct + '% utilised'"
      ></canvas>
      <p class="doughnut-label" aria-hidden="true">{{ latestPct }}% utilised</p>
    } @else {
      <p class="no-data" role="status">No bed utilisation data available.</p>
    }
  `,
  styleUrl: './bed-utilisation-chart.component.scss',
})
export class BedUtilisationChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  latestPct: number | null = null;
  chartData: ChartConfiguration<'doughnut'>['data'] = { datasets: [] };

  readonly chartOptions: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    plugins: {
      legend: { position: 'bottom' },
      title: { display: true, text: 'Bed Utilisation' },
    },
  };

  ngOnChanges(): void {
    const sorted = [...this.data].sort(
      (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
    );
    const latest = sorted.find((d) => d.bed_utilisation_pct !== null);
    this.latestPct =
      latest?.bed_utilisation_pct !== undefined && latest?.bed_utilisation_pct !== null ? Math.round(latest.bed_utilisation_pct) : null;

    if (this.latestPct !== null) {
      this.chartData = {
        labels: ['Occupied', 'Available'],
        datasets: [
          {
            data: [this.latestPct, 100 - this.latestPct],
            backgroundColor: ['rgba(66, 153, 225, 0.85)', 'rgba(226, 232, 240, 0.5)'],
            borderWidth: 1,
          },
        ],
      };
    }
  }
}
