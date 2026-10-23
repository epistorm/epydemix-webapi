import React, { useState } from 'react';
import { Check, Copy, Download } from 'lucide-react';
import { JsonView, defaultStyles } from 'react-json-view-lite';
import 'react-json-view-lite/dist/index.css';
import styles from '../Playground.module.css';
import type { Run } from '../types';
import { copyText } from '../utils';

type Props = {
  run: Run | null;
  onError: (message: string) => void;
};

export default function ResponsePanel({ run, onError }: Props) {
  const [copied, setCopied] = useState(false);

  if (!run) {
    return (
      <div className={styles.responseWrap}>
        <div className={styles.empty}>Run a simulation to see its response.</div>
      </div>
    );
  }

  const text = JSON.stringify(run.response, null, 2);

  async function handleCopy() {
    const ok = await copyText(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } else {
      onError("Couldn't copy to clipboard. Your browser may have blocked it.");
    }
  }

  function handleSave() {
    try {
      const blob = new Blob([text], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `simulation-${run!.index}-${run!.response.simulation_id ?? 'response'}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      onError(`Couldn't save file: ${(e as Error).message}`);
    }
  }

  return (
    <div className={styles.responseWrap}>
      <div className={styles.responseBox}>
        <div className={styles.responseActions}>
          <button
            className={styles.iconBtn}
            onClick={() => void handleCopy()}
            title={copied ? 'Copied!' : 'Copy response JSON'}
            aria-label="Copy response JSON"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
          <button
            className={styles.iconBtn}
            onClick={handleSave}
            title="Save response as .json"
            aria-label="Save response as JSON file"
          >
            <Download size={14} />
          </button>
        </div>
        <div className={styles.responsePre}>
          <JsonView
            data={run.response as object}
            shouldExpandNode={(level) => level < 2}
            style={{
              ...defaultStyles,
              container: styles.jsonViewContainer,
            }}
          />
        </div>
      </div>
    </div>
  );
}
