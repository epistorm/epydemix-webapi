import React, { useMemo } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Run, ShowKey } from '../types';
import { pickDates, pickSeries } from '../api';

type Props = {
  runs: Run[];
  show: ShowKey | null;
  ageGroup: string;
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
};

type Row = { x: number | string } & Record<string, number | string | null>;

export default function Chart({ runs, show, ageGroup, selectedRunId, onSelectRun }: Props) {
  const data: Row[] = useMemo(() => {
    if (!show || runs.length === 0) return [];
    const seriesByRun = runs.map((run) => {
      const s = pickSeries(run.response, show, ageGroup);
      return { run, series: s ?? [] };
    });
    const longest = seriesByRun.reduce((m, x) => Math.max(m, x.series.length), 0);
    const dates = pickDates(runs[runs.length - 1].response, show);
    const rows: Row[] = [];
    for (let i = 0; i < longest; i++) {
      const row: Row = { x: dates?.[i] ?? i };
      for (const { run, series } of seriesByRun) {
        row[run.id] = series[i] ?? null;
      }
      rows.push(row);
    }
    return rows;
  }, [runs, show, ageGroup]);

  if (runs.length === 0) {
    return <div style={{ color: 'var(--ifm-color-emphasis-500)', padding: '2rem', textAlign: 'center' }}>
      Press Run to add a trajectory.
    </div>;
  }
  if (!show) {
    return <div style={{ color: 'var(--ifm-color-emphasis-500)', padding: '2rem', textAlign: 'center' }}>
      Pick something to show.
    </div>;
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 16, right: 24, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--ifm-color-emphasis-200)" />
        <XAxis dataKey="x" tick={{ fontSize: 11 }} minTickGap={32} />
        <YAxis
          tick={{ fontSize: 11 }}
          width={72}
          tickFormatter={(v: number) =>
            typeof v === 'number' ? v.toLocaleString('en-US') : String(v)
          }
        />
        <Tooltip
          contentStyle={{
            background: 'var(--ifm-background-surface-color)',
            border: '1px solid var(--ifm-color-emphasis-300)',
            fontSize: 12,
          }}
          formatter={(v: number, name: string) => {
            const run = runs.find((r) => r.id === name);
            const formatted = typeof v === 'number' ? v.toLocaleString('en-US') : v;
            return [formatted, run ? `#${run.index} ${run.label}` : name];
          }}
        />
        {runs.map((run) => (
          <Line
            key={run.id}
            type="monotone"
            dataKey={run.id}
            name={run.id}
            stroke={run.color}
            strokeWidth={selectedRunId === run.id ? 3 : 1.75}
            dot={false}
            isAnimationActive={false}
            connectNulls
            onClick={() => onSelectRun(run.id)}
            style={{ cursor: 'pointer' }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
