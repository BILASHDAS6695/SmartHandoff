/**
 * Shared utilities for transforming KpiDataPoint[] into Chart.js datasets.
 *
 * All transformers filter out null values and map dates as labels.
 * Null values in a series are represented as Chart.js null (gap in line)
 * rather than zero to avoid misleading visualisations.
 */
import type { ChartDataset } from 'chart.js';
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
