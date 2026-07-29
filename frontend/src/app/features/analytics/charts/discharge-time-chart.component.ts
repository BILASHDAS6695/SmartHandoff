/**
 * Line chart — average discharge documentation time (minutes) over the selected date range.
 *
 * X-axis: date labels; Y-axis: minutes (auto-scaled, min 0).
 * Null values render as gaps in the line (spanGaps: false).
 *
 * Design refs:
 *   US-061 DoD — discharge_time → Line chart
 *   US-061 AC Scenario 2 — axes auto-scale to filtered data
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';
import { toDateLabels, toSingleSeriesData } from './chart.utils';

@Component({
  selector: 'app-discharge-time-chart',
  standalone: true,
  imports: [NgChartsModule],
  template: `
    @if (hasData) {
      <canvas
        baseChart
        [data]="chartData"
        [options]="chartOptions"
        type="line"
        role="img"
        [attr.aria-label]="'Discharge documentation time line chart with ' + data.length + ' data points'"
      ></canvas>
    } @else {
      <p class="no-data" role="status">No discharge time data available for this period.</p>
    }
  `,
  styleUrl: './discharge-time-chart.component.scss',
})
export class DischargeTimeChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  chartData: ChartConfiguration<'line'>['data'] = { labels: [], datasets: [] };

  readonly chartOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    spanGaps: false,
    scales: {
      y: {
        beginAtZero: true,
        title: { display: true, text: 'Minutes' },
      },
      x: { title: { display: true, text: 'Date' } },
    },
    plugins: {
      legend: { display: false },
      title: { display: true, text: 'Discharge Documentation Time (avg min)' },
    },
  };

  get hasData(): boolean {
    return this.data.some((d) => d.avg_discharge_doc_time_min !== null);
  }

  ngOnChanges(): void {
    this.chartData = {
      labels: toDateLabels(this.data),
      datasets: [
        {
          label: 'Avg discharge doc time (min)',
          data: toSingleSeriesData(this.data, 'avg_discharge_doc_time_min') as number[],
          borderColor: 'rgba(66, 153, 225, 1)',
          backgroundColor: 'rgba(66, 153, 225, 0.2)',
          fill: true,
          tension: 0.3,
        },
      ],
    };
  }
}
