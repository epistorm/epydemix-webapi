import React, { useEffect, useMemo, useState } from 'react';
import BrowserOnly from '@docusaurus/BrowserOnly';
import './patchResizeObserver';
import styles from './Playground.module.css';
import Chart from './components/Chart';
import ShowPicker from './components/ShowPicker';
import Legend from './components/Legend';
import ResponsePanel from './components/ResponsePanel';
import ApiPicker from './components/ApiPicker';
import { TEMPLATES } from './templates';
import {
  listAgeGroups,
  listShowKeys,
  runSimulation,
  showKeyId,
  stripJsonComments,
} from './api';
import type { Run, ShowKey } from './types';
import {
  PALETTE,
  PRODUCTION_URL,
  DEFAULT_CUSTOM_URL,
  STORAGE_KEY_EDITOR,
  STORAGE_KEY_API_MODE,
  STORAGE_KEY_CUSTOM_URL,
  type ApiMode,
} from './constants';
import { copyText, summarizeRequest } from './utils';

export default function SimulationsPlayground() {
  const [editorValue, setEditorValue] = useState<string>(() => TEMPLATES[0].requestText);
  const [apiMode, setApiMode] = useState<ApiMode>('production');
  const [customUrl, setCustomUrl] = useState<string>(DEFAULT_CUSTOM_URL);
  const apiBase = apiMode === 'production' ? PRODUCTION_URL : customUrl.trim();
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [show, setShow] = useState<ShowKey | null>(null);
  const [ageGroup, setAgeGroup] = useState<string>('total');
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [curlCopied, setCurlCopied] = useState(false);
  const [rightView, setRightView] = useState<'plot' | 'response'>('plot');

  // Hydrate from localStorage after mount. (localStorage is unavailable during
  // Docusaurus SSR, so we can't read it from useState initializers.)
  useEffect(() => {
    try {
      const savedEditor = window.localStorage.getItem(STORAGE_KEY_EDITOR);
      if (savedEditor) setEditorValue(savedEditor);
      const savedMode = window.localStorage.getItem(STORAGE_KEY_API_MODE);
      if (savedMode === 'production' || savedMode === 'custom') setApiMode(savedMode);
      const savedUrl = window.localStorage.getItem(STORAGE_KEY_CUSTOM_URL);
      if (savedUrl) setCustomUrl(savedUrl);
    } catch {
      // Storage may be disabled (private mode, quota, etc.); ignore.
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY_EDITOR, editorValue);
    } catch {}
  }, [editorValue]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY_API_MODE, apiMode);
    } catch {}
  }, [apiMode]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY_CUSTOM_URL, customUrl);
    } catch {}
  }, [customUrl]);

  // Available show options come from the most recent run.
  const showOptions: ShowKey[] = useMemo(() => {
    if (runs.length === 0) return [];
    return listShowKeys(runs[runs.length - 1].response);
  }, [runs]);

  const ageGroupOptions: string[] = useMemo(() => {
    if (runs.length === 0) return [];
    return listAgeGroups(runs[runs.length - 1].response, show);
  }, [runs, show]);

  // When new runs land, pick a sensible default for show + age group.
  useEffect(() => {
    if (showOptions.length === 0) return;
    if (!show || !showOptions.some((o) => showKeyId(o) === showKeyId(show))) {
      const preferred =
        showOptions.find((o) => o.kind === 'compartment' && /infect/i.test(o.name)) ??
        showOptions.find((o) => o.kind === 'compartment') ??
        showOptions[0];
      setShow(preferred);
    }
  }, [showOptions]);

  useEffect(() => {
    if (ageGroupOptions.length === 0) return;
    if (!ageGroupOptions.includes(ageGroup)) {
      setAgeGroup(ageGroupOptions.includes('total') ? 'total' : ageGroupOptions[0]);
    }
  }, [ageGroupOptions]);

  async function handleRun() {
    setError(null);
    let body: unknown;
    try {
      body = JSON.parse(stripJsonComments(editorValue));
    } catch (e) {
      setError(`Request body is not valid JSON: ${(e as Error).message}`);
      return;
    }
    setIsRunning(true);
    try {
      const response = await runSimulation(apiBase, body);
      const nextIndex = runs.reduce((m, r) => Math.max(m, r.index), 0) + 1;
      const usedColors = new Set(runs.map((r) => r.color));
      const color =
        PALETTE.find((c) => !usedColors.has(c)) ?? PALETTE[(nextIndex - 1) % PALETTE.length];
      const run: Run = {
        id:
          typeof crypto !== 'undefined' && 'randomUUID' in crypto
            ? crypto.randomUUID()
            : `${Date.now()}-${nextIndex}`,
        index: nextIndex,
        label: summarizeRequest(body),
        color,
        request: body,
        response,
      };
      setRuns((prev) => [...prev, run]);
      setSelectedRunId(run.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setIsRunning(false);
    }
  }

  function handleSelectRun(id: string) {
    const run = runs.find((r) => r.id === id);
    if (!run) return;
    setSelectedRunId(id);
    setEditorValue(JSON.stringify(run.request, null, 2));
  }

  function handleRemoveRun(id: string) {
    setRuns((prev) => prev.filter((r) => r.id !== id));
    if (selectedRunId === id) setSelectedRunId(null);
  }

  async function handleCopyCurl() {
    // Compact the current editor JSON if it parses; otherwise copy it raw.
    let body = editorValue;
    try {
      body = JSON.stringify(JSON.parse(stripJsonComments(editorValue)));
    } catch {
      // Editor isn't valid JSON; copy verbatim so users can fix it in-shell.
    }
    // Single-quote the JSON for the shell; escape any embedded single quotes.
    const quoted = `'${body.replace(/'/g, `'\\''`)}'`;
    const cmd = `curl -X POST ${apiBase}/api/v1/simulations \\
  -H 'Content-Type: application/json' \\
  -d ${quoted}`;
    const ok = await copyText(cmd);
    if (ok) {
      setCurlCopied(true);
      setTimeout(() => setCurlCopied(false), 1500);
    } else {
      setError("Couldn't copy to clipboard. Your browser may have blocked it; copy the request from the editor instead.");
    }
  }

  function handleClearAll() {
    setRuns([]);
    setSelectedRunId(null);
  }

  function handleTemplate(name: string) {
    const t = TEMPLATES.find((x) => x.name === name);
    if (!t) return;
    setEditorValue(t.requestText);
  }

  const activeRun = runs.find((r) => r.id === selectedRunId) ?? runs[runs.length - 1] ?? null;

  return (
    <div className={styles.split}>
      <div className={styles.left}>
        <div className={styles.controls}>
          <div className={styles.row}>
            <label htmlFor="tpl">Template:</label>
            <select
              id="tpl"
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) {
                  handleTemplate(e.target.value);
                  e.currentTarget.value = '';
                }
              }}
            >
              <option value="">Load…</option>
              {TEMPLATES.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </select>
            <ApiPicker
              mode={apiMode}
              customUrl={customUrl}
              onModeChange={setApiMode}
              onCustomUrlChange={setCustomUrl}
            />
          </div>
        </div>
        <div className={styles.editor}>
          <BrowserOnly fallback={<div className={styles.empty}>Loading editor…</div>}>
            {() => {
              const Editor = require('./components/Editor').default;
              return <Editor value={editorValue} onChange={setEditorValue} />;
            }}
          </BrowserOnly>
        </div>
        <div className={styles.actions}>
          <button className={styles.runBtn} onClick={handleRun} disabled={isRunning}>
            {isRunning ? 'Running…' : '▶ Run'}
          </button>
          <button
            className={styles.secondaryBtn}
            onClick={handleClearAll}
            disabled={runs.length === 0}
          >
            Clear all
          </button>
          <button
            className={styles.secondaryBtn}
            onClick={() => void handleCopyCurl()}
            title="Copy current request as a curl command"
            style={{ marginLeft: 'auto' }}
          >
            {curlCopied ? 'copied' : 'Copy curl'}
          </button>
        </div>
        {error && <div className={styles.error}>{error}</div>}
      </div>

      <div className={styles.right}>
        <div className={styles.controls}>
          <div className={styles.row}>
            {rightView === 'plot' && runs.length > 0 ? (
              <>
                <label htmlFor="show">Show:</label>
                <ShowPicker options={showOptions} value={show} onChange={setShow} />
                <label htmlFor="ageGroup">Age group:</label>
                <select
                  id="ageGroup"
                  value={ageGroup}
                  onChange={(e) => setAgeGroup(e.target.value)}
                  disabled={ageGroupOptions.length === 0}
                >
                  {ageGroupOptions.length === 0 && <option value="">—</option>}
                  {ageGroupOptions.map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
              </>
            ) : rightView === 'response' && activeRun ? (
              <span className={styles.responseHeader}>
                Response for #{activeRun.index} {activeRun.label}
              </span>
            ) : null}
            <div className={styles.viewToggle}>
              <button
                className={
                  rightView === 'plot'
                    ? `${styles.viewToggleBtn} ${styles.viewToggleBtnActive}`
                    : styles.viewToggleBtn
                }
                onClick={() => setRightView('plot')}
              >
                Plot
              </button>
              <button
                className={
                  rightView === 'response'
                    ? `${styles.viewToggleBtn} ${styles.viewToggleBtnActive}`
                    : styles.viewToggleBtn
                }
                onClick={() => setRightView('response')}
              >
                Response
              </button>
            </div>
          </div>
        </div>
        {rightView === 'plot' ? (
          <div className={styles.chartWrap}>
            <Chart
              runs={runs}
              show={show}
              ageGroup={ageGroup}
              selectedRunId={selectedRunId}
              onSelectRun={handleSelectRun}
            />
          </div>
        ) : (
          <ResponsePanel run={activeRun} onError={setError} />
        )}
        <Legend
          runs={runs}
          selectedRunId={selectedRunId}
          onSelectRun={handleSelectRun}
          onRemoveRun={handleRemoveRun}
        />
      </div>
    </div>
  );
}
