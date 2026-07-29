/**
 * Unit tests for chart.utils.ts — data transformation functions.
 *
 * Covers:
 *   - toDateLabels: correct "MMM D" format; empty array; null values skipped
 *   - toSingleSeriesData: numeric values extracted; null preserved (not coerced to 0)
 *   - toAgentSuccessDatasets: success + failure percentages sum to 100; null handled
 */
import { toAgentSuccessDatasets, toDateLabels, toSingleSeriesData } from './chart.utils';
import type { KpiDataPoint } from '../analytics.models';

const makePoint = (overrides: Partial<KpiDataPoint> = {}): KpiDataPoint => ({
  date: '2026-07-01',
  unit: 'ICU',
  avg_discharge_doc_time_min: null,
  readmission_rate_30d: null,
  med_recon_completion_rate: null,
  bed_utilisation_pct: null,
  agent_task_success_rate: null,
  ...overrides,
});

describe('toDateLabels', () => {
  it('returns empty array for empty input', () => {
    expect(toDateLabels([])).toEqual([]);
  });

  it('formats each date as "MMM D" locale string', () => {
    const data = [makePoint({ date: '2026-07-01' }), makePoint({ date: '2026-07-15' })];
    const labels = toDateLabels(data);
    // Confirm the labels are non-empty strings and contain numeric day portion
    expect(labels).toHaveLength(2);
    expect(labels[0]).toMatch(/\w{3}\s\d{1,2}/);
    expect(labels[1]).toMatch(/\w{3}\s\d{1,2}/);
  });
});

describe('toSingleSeriesData', () => {
  it('extracts numeric values for the given field', () => {
    const data = [
      makePoint({ avg_discharge_doc_time_min: 45.5 }),
      makePoint({ avg_discharge_doc_time_min: 32.0 }),
    ];
    expect(toSingleSeriesData(data, 'avg_discharge_doc_time_min')).toEqual([45.5, 32.0]);
  });

  it('preserves null values — does not coerce to 0', () => {
    const data = [
      makePoint({ avg_discharge_doc_time_min: 45.5 }),
      makePoint({ avg_discharge_doc_time_min: null }),
    ];
    const result = toSingleSeriesData(data, 'avg_discharge_doc_time_min');
    expect(result[1]).toBeNull();
  });

  it('returns all nulls for an empty metric field', () => {
    const data = [makePoint(), makePoint()];
    expect(toSingleSeriesData(data, 'readmission_rate_30d')).toEqual([null, null]);
  });
});

describe('toAgentSuccessDatasets', () => {
  it('produces two datasets: Success and Failure', () => {
    const data = [makePoint({ agent_task_success_rate: 0.85 })];
    const datasets = toAgentSuccessDatasets(data);
    expect(datasets).toHaveLength(2);
    expect(datasets[0].label).toBe('Success');
    expect(datasets[1].label).toBe('Failure');
  });

  it('success + failure sums to 100 for each data point', () => {
    const data = [
      makePoint({ agent_task_success_rate: 0.85 }),
      makePoint({ agent_task_success_rate: 0.6 }),
    ];
    const datasets = toAgentSuccessDatasets(data);
    const success = datasets[0].data as number[];
    const failure = datasets[1].data as number[];
    success.forEach((s, i) => {
      expect(s + (failure[i] as number)).toBe(100);
    });
  });

  it('handles null agent_task_success_rate — both segments null', () => {
    const data = [makePoint({ agent_task_success_rate: null })];
    const datasets = toAgentSuccessDatasets(data);
    expect(datasets[0].data[0]).toBeNull();
    expect(datasets[1].data[0]).toBeNull();
  });
});
