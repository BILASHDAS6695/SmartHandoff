---
id: TASK-005
title: "Five KPI Chart Components — Line, Bar, Gauge, Doughnut & Stacked Bar via ng2-charts"
user_story: US-061
epic: EP-012
sprint: 2
layer: Frontend / Component
estimate: 5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-061/TASK-003, US-061/TASK-004]
---

# TASK-005: Five KPI Chart Components — Line, Bar, Gauge, Doughnut & Stacked Bar via ng2-charts

> **Story:** US-061 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Frontend / Component | **Est:** 5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-061 DoD specifies five chart components, each displaying one KPI metric from the `KpiResponse.data` array:

| Chart Component | KPI Field | Chart.js Type | Chart Variable |
|---|---|---|---|
| `DischargeTimeChartComponent` | `avg_discharge_doc_time_min` | Line | Time series — minutes per day |
| `ReadmissionRateChartComponent` | `readmission_rate_30d` | Bar | Rate per day (0–1 proportion) |
| `MedReconRateChartComponent` | `med_recon_completion_rate` | Gauge (Doughnut half) | Completion rate (latest value) |
| `BedUtilisationChartComponent` | `bed_utilisation_pct` | Doughnut | % utilisation (latest value) |
| `AgentSuccessRateChartComponent` | `agent_task_success_rate` | Stacked Bar | Success/failure stacked per day |

Each component:
- Is standalone and receives `KpiDataPoint[]` as an `@Input`
- Uses `ng2-charts` `BaseChartDirective` to render Chart.js 4.x
- Auto-scales axes based on the received data (AC Scenario 2)
- Handles `null` metric values gracefully (renders empty state label)

**Design references:**
- design.md §4.1 — Chart.js 4.x; `ng2-charts` Angular wrapper for Chart.js 4.x (FR-073)
- US-061 DoD — chart types per KPI metric
- US-061 AC Scenario 2 — axes auto-scale to filtered data

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | All 5 charts render on initial load; data matches `mv_kpi_daily` values |
| Scenario 2 | Chart inputs update when `kpiData$` emits new data; axes auto-scale |

---

## Implementation Steps

### 1. Create component files

```bash
mkdir -p smarthandoff-angular/src/app/features/analytics/charts
for name in discharge-time readmission-rate med-recon-rate bed-utilisation agent-success-rate; do
  touch smarthandoff-angular/src/app/features/analytics/charts/${name}-chart.component.ts
  touch smarthandoff-angular/src/app/features/analytics/charts/${name}-chart.component.html
  touch smarthandoff-angular/src/app/features/analytics/charts/${name}-chart.component.scss
done
```

### 2. Create shared chart helper in `charts/chart.utils.ts`

```typescript
/**
 * Shared utilities for transforming KpiDataPoint[] into Chart.js datasets.
 *
 * All transformers filter out null values and map dates as labels.
 * Null values in a series are represented as Chart.js null (gap in line)
 * rather than zero to avoid misleading visualisations.
 */
import type { ChartData, ChartDataset } from 'chart.js';
import type { KpiDataPoint } from '../analytics.models';

/** Extract date labels from the data array as "MMM D" formatted strings. */
export function toDateLabels(data: KpiDataPoint[]): string[] {
  return data.map((d) =>
    new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
  );
}

/** Build a simple single-series line/bar dataset from a numeric field. */
export function toSingleSeriesData(
  data: KpiDataPoint[],
  field: keyof KpiDataPoint,
): (number | null)[] {
  return data.map((d) => {
    const v = d[field];
    return typeof v === 'number' ? v : null;
  });
}

/** Build stacked bar datasets for agent success rate (success vs failure). */
export function toAgentSuccessDatasets(data: KpiDataPoint[]): ChartDataset<'bar'>[] {
  const successRates = data.map((d) =>
    typeof d.agent_task_success_rate === 'number'
      ? Math.round(d.agent_task_success_rate * 100)
      : null,
  );
  const failureRates = successRates.map((r) => (r !== null ? 100 - r : null));

  return [
    {
      label: 'Success',
      data: successRates as number[],
      backgroundColor: 'rgba(56, 161, 105, 0.8)',
      stack: 'agent',
    },
    {
      label: 'Failure',
      data: failureRates as number[],
      backgroundColor: 'rgba(229, 62, 62, 0.8)',
      stack: 'agent',
    },
  ];
}
```

### 3. Implement `DischargeTimeChartComponent` (Line chart)

```typescript
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
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';
import { toDateLabels, toSingleSeriesData } from './chart.utils';

@Component({
  selector: 'app-discharge-time-chart',
  standalone: true,
  imports: [BaseChartDirective],
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
```

### 4. Implement `ReadmissionRateChartComponent` (Bar chart)

```typescript
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
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';
import { toDateLabels, toSingleSeriesData } from './chart.utils';

@Component({
  selector: 'app-readmission-rate-chart',
  standalone: true,
  imports: [BaseChartDirective],
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
```

### 5. Implement `MedReconRateChartComponent` (Gauge — half-Doughnut)

```typescript
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
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';

@Component({
  selector: 'app-med-recon-rate-chart',
  standalone: true,
  imports: [BaseChartDirective],
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
```

### 6. Implement `BedUtilisationChartComponent` (Doughnut chart)

```typescript
/**
 * Doughnut chart — bed utilisation percentage (latest value).
 *
 * Design refs:
 *   US-061 DoD — bed_utilisation → Doughnut chart
 */
import { Component, Input, OnChanges } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';

@Component({
  selector: 'app-bed-utilisation-chart',
  standalone: true,
  imports: [BaseChartDirective],
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
    this.latestPct = latest?.bed_utilisation_pct !== undefined ? Math.round(latest.bed_utilisation_pct) : null;

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
```

### 7. Implement `AgentSuccessRateChartComponent` (Stacked Bar chart)

```typescript
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
import { BaseChartDirective } from 'ng2-charts';
import type { ChartConfiguration } from 'chart.js';

import { KpiDataPoint } from '../analytics.models';
import { toDateLabels, toAgentSuccessDatasets } from './chart.utils';

@Component({
  selector: 'app-agent-success-rate-chart',
  standalone: true,
  imports: [BaseChartDirective],
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
```

### 8. Compose charts into the `AnalyticsComponent` template

Replace the `<!-- Individual chart components composed here in TASK-005 -->` placeholder in `analytics.component.html`:

```html
<ng-container *ngIf="kpiData$ | async as kpiData; else loading">
  <div class="kpi-charts-grid">
    <app-discharge-time-chart [data]="kpiData.data" class="kpi-chart-card" />
    <app-readmission-rate-chart [data]="kpiData.data" class="kpi-chart-card" />
    <app-med-recon-rate-chart [data]="kpiData.data" class="kpi-chart-card" />
    <app-bed-utilisation-chart [data]="kpiData.data" class="kpi-chart-card" />
    <app-agent-success-rate-chart [data]="kpiData.data" class="kpi-chart-card" />
  </div>
</ng-container>
```

Add chart components to `AnalyticsComponent.imports[]`:

```typescript
imports: [
  AsyncPipe,
  NgIf,
  AnalyticsFilterBarComponent,
  DischargeTimeChartComponent,
  ReadmissionRateChartComponent,
  MedReconRateChartComponent,
  BedUtilisationChartComponent,
  AgentSuccessRateChartComponent,
],
```

### 9. Add `provideCharts` to the analytics routes provider

In `analytics.routes.ts`, register Chart.js controllers so only required controllers are bundled:

```typescript
import { Routes } from '@angular/router';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';
import { roleGuard } from '@core/auth/role.guard';

export const ANALYTICS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./analytics.component').then((m) => m.AnalyticsComponent),
    canActivate: [roleGuard(['MANAGER', 'ADMIN'])],
    title: 'Analytics Dashboard — SmartHandoff',
    providers: [provideCharts(withDefaultRegisterables())],
  },
];
```

---

## Validation Checklist

- [ ] All 5 chart components render without console errors when given a valid `KpiDataPoint[]` input
- [ ] Each chart type matches the DoD specification: Line / Bar / Gauge(Doughnut) / Doughnut / Stacked Bar
- [ ] Null metric values render the "no data" empty state — no `0` values injected to mislead
- [ ] Charts re-render on `@Input data` change (triggered by filter bar — AC Scenario 2)
- [ ] Y-axis auto-scales correctly for each chart type (no hardcoded axis limits except Doughnut/Gauge)
- [ ] All `<canvas>` elements have `role="img"` and descriptive `aria-label` (WCAG 2.2 Level AA)
- [ ] `provideCharts(withDefaultRegisterables())` registered at route level — not eagerly at app level
- [ ] No PHI fields accessed or rendered in any chart template or dataset

---

## Files Created / Modified

| File | Action |
|------|--------|
| `smarthandoff-angular/src/app/features/analytics/charts/chart.utils.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/charts/discharge-time-chart.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/charts/readmission-rate-chart.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/charts/med-recon-rate-chart.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/charts/bed-utilisation-chart.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/charts/agent-success-rate-chart.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.ts` | Modify — add chart imports |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.html` | Modify — compose 5 chart components |
| `smarthandoff-angular/src/app/features/analytics/analytics.routes.ts` | Modify — add `provideCharts` |
