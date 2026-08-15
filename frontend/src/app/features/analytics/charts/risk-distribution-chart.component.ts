/**
 * Readmission Risk Distribution — doughnut chart showing the relative share
 * of high, medium, and low risk encounters over the selected range.
 *
 * Data is aggregated across units when multiple units are present.
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';

@Component({
  selector: 'app-risk-distribution-chart',
  standalone: true,
  imports: [NgChartsModule],
  template: `
    @if (hasData) {
      <div class="donut-wrap">
        <canvas
          baseChart
          [data]="chartData"
          [options]="chartOptions"
          type="doughnut"
          role="img"
          aria-label="Readmission risk distribution doughnut chart"
        ></canvas>
      </div>
    } @else {
      <p class="no-data" role="status">No risk distribution data available for this period.</p>
    }
  `,
  styleUrl: './risk-distribution-chart.component.scss',
})
export class RiskDistributionChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  chartData: ChartConfiguration<'doughnut'>['data'] = { labels: [], datasets: [] };

  readonly chartOptions: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'right' },
      title: { display: true, text: 'Readmission Risk Distribution' },
    },
  };

  get hasData(): boolean {
    return this.data.some(
      (d) => (d.high_risk_count ?? 0) + (d.medium_risk_count ?? 0) + (d.low_risk_count ?? 0) > 0,
    );
  }

  ngOnChanges(): void {
    let high = 0;
    let medium = 0;
    let low = 0;

    for (const point of this.data) {
      high += point.high_risk_count ?? 0;
      medium += point.medium_risk_count ?? 0;
      low += point.low_risk_count ?? 0;
    }

    this.chartData = {
      labels: ['High risk (>0.7)', 'Medium (0.3–0.7)', 'Low risk (<0.3)'],
      datasets: [
        {
          data: [high, medium, low],
          backgroundColor: [
            'rgba(220, 38, 38, 0.8)',
            'rgba(217, 119, 6, 0.8)',
            'rgba(22, 163, 74, 0.8)',
          ],
          borderColor: [
            'rgba(220, 38, 38, 1)',
            'rgba(217, 119, 6, 1)',
            'rgba(22, 163, 74, 1)',
          ],
          borderWidth: 1,
        },
      ],
    };
  }
}
