/**
 * Discharge Volume chart — count of discharges per day over the selected range.
 *
 * Data is aggregated across units when multiple units are present in the input.
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';

@Component({
  selector: 'app-discharge-volume-chart',
  standalone: true,
  imports: [NgChartsModule],
  host: { style: 'display: block; height: 220px;' },
  template: `
    @if (hasData) {
      <canvas
        baseChart
        [data]="chartData"
        [options]="chartOptions"
        type="bar"
        role="img"
        [attr.aria-label]="'Discharge volume bar chart with ' + labels.length + ' data points'"
      ></canvas>
    } @else {
      <p class="no-data" role="status">No discharge volume data available for this period.</p>
    }
  `,
  styleUrl: './discharge-time-chart.component.scss',
})
export class DischargeVolumeChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  labels: string[] = [];
  chartData: ChartConfiguration<'bar'>['data'] = { labels: [], datasets: [] };

  readonly chartOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    scales: {
      y: {
        beginAtZero: true,
        title: { display: true, text: 'Discharges' },
      },
      x: { title: { display: true, text: 'Date' } },
    },
    plugins: {
      legend: { display: false },
      title: { display: true, text: 'Discharge Volume' },
    },
  };

  get hasData(): boolean {
    return this.data.some((d) => (d.discharge_count ?? 0) > 0);
  }

  ngOnChanges(): void {
    const grouped = new Map<string, number>();
    for (const point of this.data) {
      const current = grouped.get(point.date) ?? 0;
      grouped.set(point.date, current + (point.discharge_count ?? 0));
    }

    const sortedDates = Array.from(grouped.keys()).sort();
    this.labels = sortedDates.map((d) =>
      new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    );

    this.chartData = {
      labels: this.labels,
      datasets: [
        {
          label: 'Discharges',
          data: sortedDates.map((d) => grouped.get(d) ?? 0),
          backgroundColor: 'rgba(37, 99, 235, 0.7)',
          borderColor: 'rgba(37, 99, 235, 1)',
          borderWidth: 1,
        },
      ],
    };
  }
}
