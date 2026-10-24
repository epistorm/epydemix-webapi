import { expect, test } from 'bun:test';
import { buildChartData } from '../src/playground/api';

const show = { kind: 'compartment', name: 'Infected' };
function run(id, dates, values) {
  return {
    id,
    response: {
      status: 'completed',
      results: {
        compartments: { dates, data: { Infected: { total: { '0.5': values } } } },
      },
    },
  };
}

test('runs align by their own dates rather than their array positions', () => {
  const data = buildChartData([
    run('january', ['2025-01-01', '2025-01-02'], [10, 20]),
    run('february', ['2025-02-01'], [30]),
  ], show, 'total');
  expect(data).toEqual([
    { x: '2025-01-01', january: 10 },
    { x: '2025-01-02', january: 20 },
    { x: '2025-02-01', february: 30 },
  ]);
});

test('different output frequencies join only on the same dates', () => {
  const daily = run('daily', ['2025-01-05', '2025-01-06', '2025-01-12'], [1, 2, 3]);
  const weekly = run('weekly', ['2025-01-05', '2025-01-12'], [4, 5]);
  expect(buildChartData([weekly, daily], show, 'total')).toEqual([
    { x: '2025-01-05', weekly: 4, daily: 1 },
    { x: '2025-01-06', daily: 2 },
    { x: '2025-01-12', weekly: 5, daily: 3 },
  ]);
});

test('parameter series use their own time axis', () => {
  const input = run('run', ['2025-01-05'], [1]);
  input.response.results.parameters = {
    dates: ['2025-01-01', '2025-01-02'], data: { beta: { A: [0.2, 0.1] } },
  };
  expect(buildChartData([input], { kind: 'parameter', name: 'beta' }, 'A')).toEqual([
    { x: '2025-01-01', run: 0.2 }, { x: '2025-01-02', run: 0.1 },
  ]);
});

test('subdaily timestamps remain distinct chart points', () => {
  const dates = ['2025-01-01T00:00:00', '2025-01-01T12:00:00', '2025-01-02T00:00:00'];
  const data = buildChartData([run('halfday', dates, [10, 20, 30])], show, 'total');
  expect(data.map(row => row.x)).toEqual(dates);
  expect(data.map(row => row.halfday)).toEqual([10, 20, 30]);
});
