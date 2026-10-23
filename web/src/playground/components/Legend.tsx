import React from 'react';
import styles from '../Playground.module.css';
import type { Run } from '../types';

type Props = {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
  onRemoveRun: (id: string) => void;
};

export default function Legend({ runs, selectedRunId, onSelectRun, onRemoveRun }: Props) {
  if (runs.length === 0) {
    return (
      <div className={styles.legend}>
        <div className={styles.empty} style={{ padding: '0.5rem' }}>
          No runs yet.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.legend}>
      {runs.map((run) => (
        <div
          key={run.id}
          className={
            selectedRunId === run.id
              ? `${styles.legendRow} ${styles.legendRowSelected}`
              : styles.legendRow
          }
          onClick={() => onSelectRun(run.id)}
        >
          <span className={styles.swatch} style={{ background: run.color }} />
          <span className={styles.legendLabel}>
            #{run.index} {run.label}
          </span>
          <button
            className={styles.legendRemove}
            onClick={(e) => {
              e.stopPropagation();
              onRemoveRun(run.id);
            }}
            title="Remove run"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
