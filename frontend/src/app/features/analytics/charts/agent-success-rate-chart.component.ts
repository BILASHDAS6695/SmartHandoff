/**
 * Stacked bar chart — agent task success vs failure rate per day.
 *
 * Each bar = 100%; green segment = success %, red segment = failure %.
 * Null values for a day are skipped (bar not rendered for that date).
 *
 * Design refs:
 *   US-061 DoD — agent_success_rate → Stacked Bar chart
 */
import { Component, Input, OnChanges } from '@angular/core';
import { NgChartsModule } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';
import { toDateLabels, toAgentSuccessDatasets } from './chart.utils';

@Component({
  selector: 'app-agent-success-rate-chart',
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
        [attr.aria-label]="'Agent task success rate stacked bar chart with ' + data.length + ' data points'"
      ></canvas>
    } @else {
      <p class="no-data" role="status">No agent task data available for this period.</p>
    }
  `,
  styleUrl: './agent-success-rate-chart.component.scss',
})
export class AgentSuccessRateChartComponent implements OnChanges {
  @Input() data: KpiDataPoint[] = [];

  chartData: ChartConfiguration<'bar'>['data'] = { labels: [], datasets: [] };

  readonly chartOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    scales: {
      x: { stacked: true, title: { display: true, text: 'Date' } },
      y: {
        stacked: true,
        min: 0,
        max: 100,
        title: { display: true, text: 'Agent Tasks (%)' },
      },
    },
    plugins: {
      title: { display: true, text: 'Agent Task Success Rate' },
    },
  };

  get hasData(): boolean {
    return this.data.some((d) => d.agent_task_success_rate !== null);
  }

  ngOnChanges(): void {
    this.chartData = {
      labels: toDateLabels(this.data),
      datasets: toAgentSuccessDatasets(this.data),
    };
  }
}
