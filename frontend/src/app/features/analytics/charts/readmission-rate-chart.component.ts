/**
 * Bar chart — 30-day readmission rate per day.
 *
 * Y-axis: percentage (proportion × 100); X-axis: date.
 * Null values render as 0-height bars with tooltip "No data".
 *
 * Design refs:
 *   US-061 DoD — readmission_rate → Bar chart
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';
import { toDateLabels, toSingleSeriesData } from './chart.utils';

@Component({
  selector: 'app-readmission-rate-chart',
  standalone: true,
  imports: [NgChartsModule],
  template: `
    @if (hasData) {
      <canvas
        baseChart
        [data]="chartData"
        [options]="chartOptions"
        type="bar"
        role="img"
        [attr.aria-label]="'30-day readmission rate bar chart with ' + data.length + ' data points'"
      ></canvas>
    } @else {
      <p class="no-data" role="status">No readmission rate data available for this period.</p>
    }
  `,
  styleUrl: './readmission-rate-chart.component.scss',
})
export class ReadmissionRateChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  chartData: ChartConfiguration<'bar'>['data'] = { labels: [], datasets: [] };

  readonly chartOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    scales: {
      y: {
        beginAtZero: true,
        max: 100,
        title: { display: true, text: 'Readmission Rate (%)' },
      },
      x: { title: { display: true, text: 'Date' } },
    },
    plugins: {
      title: { display: true, text: '30-Day Readmission Rate' },
    },
  };

  get hasData(): boolean {
    return this.data.some((d) => d.readmission_rate_30d !== null);
  }

  ngOnChanges(): void {
    const rawRates = toSingleSeriesData(this.data, 'readmission_rate_30d');
    this.chartData = {
      labels: toDateLabels(this.data),
      datasets: [
        {
          label: 'Readmission rate (%)',
          data: rawRates.map((r) => (r !== null ? Math.round(r * 100) : 0)) as number[],
          backgroundColor: 'rgba(237, 137, 54, 0.8)',
        },
      ],
    };
  }
}
